import os
import time
import datetime
import json
import sqlite3
import requests
from dotenv import load_dotenv
from binance.client import Client

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

client = Client(BINANCE_KEY, BINANCE_SECRET)

LIVE_MODE = False
START_BALANCE = 100.12493175
MAX_INVESTED_PER_DAY = START_BALANCE * 0.2
DB_PATH = "prices.db"
POSITION_FILE = "positions.json"
BALANCE_FILE = "balance.json"
TRADE_LOG_FILE = "trade_log.json"
TRADING_PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "ADAUSDT", "DOGEUSDT", "LINKUSDT", "MATICUSDT", "DOTUSDT"
]

bad_words = ["lawsuit", "ban", "hack", "crash", "regulation", "investigation"]
good_words = ["surge", "rally", "gain", "partnership", "bullish", "upgrade", "adoption"]

def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"Telegram error: {e}")

def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Failed to load {path}: {e} — resetting.")
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                symbol TEXT, timestamp TEXT, price REAL
            )
        """)

def save_price(symbol, price):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT INTO prices (symbol, timestamp, price) VALUES (?, ?, ?)",
                         (symbol, now, price))
            conn.commit()
        print(f"💾 Saved {symbol} at ${price:.2f}")
    except Exception as e:
        print(f"❌ DB save error for {symbol}: {e}")

def get_price(symbol):
    try:
        return float(client.get_symbol_ticker(symbol=symbol)['price'])
    except:
        return None

def get_news_headlines(symbol, limit=5):
    try:
        query = symbol.replace("USDT", "")
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "apiKey": NEWSAPI_KEY,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": limit
        }
        r = requests.get(url, params=params).json()
        return [a["title"] for a in r.get("articles", []) if "title" in a]
    except Exception as e:
        print(f"❌ NewsAPI error for {symbol}: {e}")
        return []

def log_trade(symbol, typ, qty, price):
    log = load_json(TRADE_LOG_FILE, [])
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    log.append({"symbol": symbol, "type": typ, "qty": qty, "price": price, "timestamp": timestamp})
    save_json(TRADE_LOG_FILE, log)

def trade():
    positions = load_json(POSITION_FILE, {})
    balance = load_json(BALANCE_FILE, {"usdt": START_BALANCE})
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')

    for symbol in TRADING_PAIRS:
        price = get_price(symbol)
        if not price:
            print(f"⚠️ No price for {symbol}")
            continue

        save_price(symbol, price)
        print(f"🔍 {symbol} @ ${price:.2f}")

        headlines = get_news_headlines(symbol)
        if any(any(bad in h.lower() for bad in bad_words) for h in headlines):
            print(f"🚫 {symbol} blocked by negative news")
            continue
        if not any(any(good in h.lower() for good in good_words) for h in headlines):
            print(f"🟡 {symbol} skipped — no strong positive news")
           

# Total currently invested across all open positions
        current_invested = sum(p["qty"] * get_price(sym) for sym, p in positions.items())
        remaining_allowance = MAX_INVESTED_PER_DAY - current_invested

        if remaining_allowance <= 0:
            print(f"🔒 Max daily investment reached. Skipping {symbol}")
            continue

# Determine how much of remaining allowance to use
        trade_usdt = min(remaining_allowance, balance["usdt"] * 0.25)
        qty = round(trade_usdt / price, 6)


        if symbol not in positions:
            if qty * price > balance["usdt"]:
                print(f"❌ Insufficient balance for {symbol}")
                continue

            positions[symbol] = {"type": "LONG", "qty": qty, "entry": price}
            balance["usdt"] -= qty * price
            log_trade(symbol, "BUY", qty, price)

            total_cost = qty * price
            send(f"🟢 BUY {qty} {symbol} at ${price:.2f} — Total: ${total_cost:.2f} USDT — {now}")
            print(f"✅ BUY {qty} {symbol} at ${price:.2f} (${total_cost:.2f})")

        else:
            pos = positions[symbol]
            entry = pos["entry"]
            qty = pos["qty"]
            pnl = ((price - entry) / entry) * 100
            profit = (price - entry) * qty

            print(f"📈 {symbol} Entry ${entry:.2f} → Now ${price:.2f} | PnL: {pnl:.2f}%")

            if pnl >= 0.5:
                balance["usdt"] += qty * price
                del positions[symbol]
                log_trade(symbol, "CLOSE-LONG", qty, price)

                send(
                    f"✅ CLOSE {symbol} at ${price:.2f} — Profit: ${profit:.2f} USDT (+{pnl:.2f}%) — {now}"
                )
                print(f"✅ CLOSE {symbol} at ${price:.2f} | Profit: ${profit:.2f} USDT (+{pnl:.2f}%)")
                invested = sum(p["qty"] * get_price(sym) for sym, p in positions.items())
                total = balance["usdt"] + invested
                send(f"📊 Updated Balance: ${total:.2f} USDT — {now}")


    save_json(POSITION_FILE, positions)
    save_json(BALANCE_FILE, balance)

    invested = sum(p["qty"] * get_price(sym) for sym, p in positions.items())
    total = balance["usdt"] + invested
    print(f"[{now}] Net balance: ${total:.2f}")
    send(f"📊 Updated Balance: ${total:.2f} USDT — {now}")



def place_order(symbol, side, qty):
    if LIVE_MODE:
        return client.create_order(
            symbol=symbol,
            side=side.upper(),
            type="MARKET",
            quantity=qty
        )
    else:
        print(f"[SIMULATED] {side} {qty} {symbol}")
        return {"simulated": True, "symbol": symbol, "side": side, "qty": qty}

def main():
    try:
        init_db()
        print("🤖 Trading bot started")
        send("🤖 Trading bot running with news filtering")

        while True:
            try:
                trade()
            except Exception as e:
                print(f"ERROR in trade(): {e}")
                send(f"⚠️ Error in trade(): {e}")
            time.sleep(300)
    except Exception as e:
        print(f"❌ Startup failed: {e}")
        send(f"🚨 Bot failed to start: {e}")

if __name__ == "__main__":
    main()
