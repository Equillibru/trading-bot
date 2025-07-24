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
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    for symbol in TRADING_PAIRS:
        price = get_price(symbol)
        if not price:
            print(f"⚠️ {symbol} price unavailable")
            continue

        save_price(symbol, price)
        print(f"🔍 {symbol} at ${price:.2f}")

        qty = round((balance["usdt"] * 0.5) / price, 6)

        # Forced test trade (only once)
        if symbol not in positions:
            if qty * price > balance["usdt"]:
                print(f"💸 Not enough balance for {symbol}")
                continue

            # FORCED BUY
            place_order(symbol, "BUY", qty)
            positions[symbol] = {"type": "LONG", "qty": qty, "entry": price}
            balance["usdt"] -= qty * price
            log_trade(symbol, "FORCED-BUY", qty, price)
            send(f"🧪 FORCED BUY {qty} {symbol} at ${price:.2f} — {now}")
            print(f"✅ FORCED BUY {qty} {symbol} at ${price:.2f}")
            break  # Only force one trade

        elif symbol in positions:
            pos = positions[symbol]
            entry = pos["entry"]
            qty = pos["qty"]
            pnl = ((price - entry) / entry) * 100

            print(f"📈 {symbol} entry ${entry:.2f} → now ${price:.2f} | PnL: {pnl:.2f}%")

            if pnl >= 0.1:
                place_order(symbol, "SELL", qty)
                balance["usdt"] += qty * price
                log_trade(symbol, "CLOSE-LONG", qty, price)
                send(f"✅ CLOSE {symbol} at ${price:.2f} (+{pnl:.2f}%)")
                del positions[symbol]

    save_json(POSITION_FILE, positions)
    save_json(BALANCE_FILE, balance)

    invested = sum(p["qty"] * get_price(sym) for sym, p in positions.items())
    total = balance["usdt"] + invested
    print(f"[{now}] Net balance: ${total:.2f}")

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
