import os
import time
import datetime
import json
import sqlite3
import requests
import statistics
from dotenv import load_dotenv
from binance.client import Client

# Load API keys
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")

# Binance
client = Client(BINANCE_KEY, BINANCE_SECRET)

# Settings
LIVE_MODE = False
START_BUDGET = 100.0
POSITION_FILE = "positions.json"
BALANCE_FILE = "balance.json"
DB_PATH = "prices.db"
TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT"]

# --- Telegram ---
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except:
        pass

# --- JSON ---
def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# --- SQLite ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS prices (
            symbol TEXT, timestamp TEXT, price REAL)""")

def save_price(symbol, price):
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO prices (symbol, timestamp, price) VALUES (?, ?, ?)",
                     (symbol, now, price))
        conn.commit()

# --- Price Analysis ---
def get_klines(symbol, interval, limit):
    try:
        return client.get_klines(symbol=symbol, interval=interval, limit=limit)
    except:
        return []

def analyze_buy_opportunity(symbol):
    klines_1h = get_klines(symbol, Client.KLINE_INTERVAL_1HOUR, 24*7)
    if len(klines_1h) < 24 * 7:
        return False

    closes = [float(k[4]) for k in klines_1h]
    volumes = [float(k[5]) for k in klines_1h]

    now = closes[-1]
    hour_ago = closes[-2]
    day_ago = closes[-24]
    week_ago = closes[0]

    # 1h trend
    one_hour_change = ((now - hour_ago) / hour_ago) * 100
    if one_hour_change < 1:
        return False

    # 7d trend
    week_change = ((now - week_ago) / week_ago) * 100
    if week_change < 3:
        return False

    # Volume increasing
    recent_vol = sum(volumes[-6:])
    prev_vol = sum(volumes[-12:-6])
    if recent_vol <= prev_vol:
        return False

    # Volatility check (low std dev)
    volatility = statistics.stdev(closes[-12:])
    if volatility / now > 0.02:  # >2% std dev
        return False

    return True

# --- Trade Execution ---
def get_price(symbol):
    try:
        return float(client.get_symbol_ticker(symbol=symbol)["price"])
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
        return {"simulated": True, "symbol": symbol, "side": side, "qty": qty}

# --- Trading Logic ---
def trade():
    positions = load_json(POSITION_FILE, {})
    balance = load_json(BALANCE_FILE, {"usdt": START_BUDGET})
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    for symbol in TRADING_PAIRS:
        price = get_price(symbol)
        if not price:
            continue

        save_price(symbol, price)

        # BUY logic (high-confidence only)
        if symbol not in positions and analyze_buy_opportunity(symbol):
            usdt_available = balance["usdt"]
            allocation = usdt_available * 0.5
            qty = round(allocation / price, 6)
            if qty * price > usdt_available:
                continue
            place_order(symbol, "BUY", qty)
            balance["usdt"] -= qty * price
            positions[symbol] = {"qty": qty, "buy_price": price}
            send(f"🟢 BUY {qty} {symbol} at ${price:.2f} — {now}")

        # SELL logic (≥1% gain or signal reversal)
        elif symbol in positions:
            qty = positions[symbol]["qty"]
            entry = positions[symbol]["buy_price"]
            change = ((price - entry) / entry) * 100
            if change >= 1.0:
                place_order(symbol, "SELL", qty)
                balance["usdt"] += qty * price
                send(f"🔴 SELL {qty} {symbol} at ${price:.2f} — P/L: {change:.2f}%")
                del positions[symbol]

    # Save state
    save_json(POSITION_FILE, positions)
    save_json(BALANCE_FILE, balance)

    # Report portfolio
    invested = sum(p["qty"] * get_price(sym) for sym, p in positions.items())
    total = balance["usdt"] + invested
    change = ((total - START_BUDGET) / START_BUDGET) * 100
    print(f"[{now}] Total value: ${total:.2f} ({change:.2f}%)")
    if change >= 3.0:
        send(f"🎉 Daily profit target reached! +{change:.2f}%")

# --- Main ---
def main():
    init_db()
    send("🤖 Smart trading bot started (confidence-based)")
    while True:
        try:
            trade()
        except Exception as e:
            send(f"⚠️ Error: {e}")
        time.sleep(300)

if __name__ == "__main__":
    main()
