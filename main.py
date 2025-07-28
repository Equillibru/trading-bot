import os
import time
import datetime
import json
import sqlite3
import requests
import math
from dotenv import load_dotenv
from binance.client import Client

# === Load environment ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

client = Client(BINANCE_KEY, BINANCE_SECRET)

LIVE_MODE = True
START_BALANCE = 100.32  # Example starting balance
DAILY_MAX_INVEST = START_BALANCE * 0.20
POSITION_FILE = "positions.json"
BALANCE_FILE = "balance.json"
TRADE_LOG_FILE = "trade_log.json"
TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "ENAUSDT", "PENGUUSDT", "TRXUSDT", 
                 "ADAUSDT", "PEPEUSDT", "BONKUSDT", "LTCUSDT", "BNBUSDT", "AVAXUSDT", "XLMUSDT", "UNIUSDT", 
                 "CFXUSDT", "AAVEUSDT", "WIFUSDT", "KERNELUSDT", "BCHUSDT", "ARBUSDT", "ENSUSDT", 
                 "DOTUSDT", "CKBUSDT", "LINKUSDT", "TONUSDT", "NEARUSDT", "ETCUSDT", "CAKEUSDT", 
                 "SHIBUSDT", "OPUSDT"]

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
    except:
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def get_price(symbol):
    try:
        return float(client.get_symbol_ticker(symbol=symbol)['price'])
    except:
        return None

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
        return {"simulated": True}

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
    except:
        return []

def log_trade(symbol, typ, qty, price):
    log = load_json(TRADE_LOG_FILE, [])
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    log.append({"symbol": symbol, "type": typ, "qty": qty, "price": price, "timestamp": timestamp})
    save_json(TRADE_LOG_FILE, log)

def save_price(symbol, price):
    pass  # implement if using DB

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
            #continue

        # Daily max check
        current_invested = sum(p["qty"] * get_price(sym) for sym, p in positions.items())
        remaining_allowance = DAILY_MAX_INVEST - current_invested
        if remaining_allowance <= 0:
            print(f"🔒 Daily investment cap reached — skipping {symbol}")
            continue

        # Calculate qty (25% of USDT or remaining cap)
        trade_usdt = min(balance["usdt"] * 0.25, remaining_allowance)
        qty = math.floor((trade_usdt / price) * 1e6) / 1e6
        if qty * price < 0.25:
          print(f"⚠️ {symbol} skipped — trade value {qty * price:.4f} USDT below 0.25 minimum")
          continue

        print(f"🔢 {symbol} → trade_usdt: {trade_usdt:.4f}, price: {price:.2f}, qty: {qty}")
        if qty <= 0:
            print(f"❌ Qty for {symbol} is zero — skipping")
            continue

        if symbol not in positions:
            if qty <= 0 or qty * price > balance["usdt"]:
                print(f"❌ Cannot buy {symbol} — qty too low or insufficient funds")
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

                send(f"✅ CLOSE {symbol} at ${price:.2f} — Profit: ${profit:.2f} USDT (+{pnl:.2f}%) — {now}")
                print(f"✅ CLOSE {symbol} at ${price:.2f} | Profit: ${profit:.2f} USDT (+{pnl:.2f}%)")

        # Update and report balance
        invested = sum(p["qty"] * get_price(sym) for sym, p in positions.items())
        total = balance["usdt"] + invested
        send(f"📊 Updated Balance: ${total:.2f} USDT — {now}")

    save_json(POSITION_FILE, positions)
    save_json(BALANCE_FILE, balance)

def main():
    print("🤖 Trading bot started.")
    send("🤖 Trading bot is live.")
    while True:
        try:
            trade()
        except Exception as e:
            print(f"ERROR: {e}")
            send(f"⚠️ Bot error: {e}")
        time.sleep(300)

if __name__ == "__main__":
    main()
