import os
import time
import datetime
import json
import sqlite3
import requests
import statistics
from dotenv import load_dotenv
from binance.client import Client

# Load environment
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")

# Binance client
client = Client(BINANCE_KEY, BINANCE_SECRET)

# Settings
LIVE_MODE = False
START_BUDGET = 100.0
DB_PATH = "prices.db"
POSITION_FILE = "positions.json"
BALANCE_FILE = "balance.json"
TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT"]

# --- Telegram Alerts ---
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"Telegram error: {e}")

# --- File I/O ---
def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# --- SQLite Storage ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                symbol TEXT,
                timestamp TEXT,
                price REAL
            )
        """)

def save_price(symbol, price):
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO prices (symbol, timestamp, price) VALUES (?, ?, ?)",
                     (symbol, now, price))
        conn.commit()

# --- Market Data ---
def get_klines(symbol, interval, limit):
    try:
        return client.get_klines(symbol=symbol, interval=interval, limit=limit)
    except:
        return []

def get_price(symbol):
    try:
        return float(client.get_symbol_ticker(symbol=symbol)['price'])
    except:
        return None

# --- Trade Placement ---
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

# --- Opportunity Analysis ---
def analyze_opportunity(symbol):
    klines = get_klines(symbol, Client.KLINE_INTERVAL_1HOUR, 168)
    if len(klines) < 168:
        return None

    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]

    now = closes[-1]
    hour_ago = closes[-2]
    three_days_ago = closes[-72]
    week_ago = closes[0]

    # % changes
    one_hour = ((now - hour_ago) / hour_ago) * 100
    three_day = ((now - three_days_ago) / three_days_ago) * 100
    seven_day = ((now - week_ago) / week_ago) * 100

    # Volume and volatility
    vol_recent = sum(volumes[-6:])
    vol_prev = sum(volumes[-12:-6])
    volatility = statistics.stdev(closes[-24:]) / now

    if vol_recent <= vol_prev:
        return None  # no volume growth

    if volatility > 0.02:
        return None  # too volatile

    # Decision
    if one_hour >= 1 and three_day >= 2 and seven_day >= 3:
        return "BUY"
    elif one_hour <= -1 and three_day <= -2 and seven_day <= -3:
        return "SHORT"
    return None

# --- Trade Execution Logic ---
def trade():
    positions = load_json(POSITION_FILE, {})
    balance = load_json(BALANCE_FILE, {"usdt": START_BUDGET})
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    for symbol in TRADING_PAIRS:
        price = get_price(symbol)
        if not price:
            continue

        save_price(symbol, price)
        signal = analyze_opportunity(symbol)

        # --- BUY ---
        if signal == "BUY" and symbol not in positions:
            usdt_available = balance["usdt"]
            allocation = usdt_available * 0.5
            qty = round(allocation / price, 6)
            if qty * price > usdt_available:
                continue
            place_order(symbol, "BUY", qty)
            balance["usdt"] -= qty * price
            positions[symbol] = {"type": "LONG", "qty": qty, "entry": price}
            send(f"🟢 BUY {qty} {symbol} at ${price:.2f} — {now}")

        # --- SHORT ---
        elif signal == "SHORT" and symbol not in positions:
            usdt_available = balance["usdt"]
            allocation = usdt_available * 0.5
            qty = round(allocation / price, 6)
            if qty * price > usdt_available:
                continue
            place_order(symbol, "SELL", qty)
            balance["usdt"] -= qty * price
            positions[symbol] = {"type": "SHORT", "qty": qty, "entry": price}
            send(f"🔻 SHORT {qty} {symbol} at ${price:.2f} — {now}")

        # --- CLOSE TRADE IF PNL >= 1% ---
        elif symbol in positions:
            entry = positions[symbol]["entry"]
            qty = positions[symbol]["qty"]
            side = positions[symbol]["type"]

            pnl = ((price - entry) / entry) * 100 if side == "LONG" else ((entry - price) / entry) * 100

            if pnl >= 1:
                action = "SELL" if side == "LONG" else "BUY"
                place_order(symbol, action, qty)
                balance["usdt"] += qty * price
                send(f"✅ CLOSED {side} {qty} {symbol} at ${price:.2f} — P/L: {pnl:.2f}%")
                del positions[symbol]

    save_json(POSITION_FILE, positions)
    save_json(BALANCE_FILE, balance)

    invested = sum(p["qty"] * get_price(sym) for sym, p in positions.items())
    total = balance["usdt"] + invested
    change = ((total - START_BUDGET) / START_BUDGET) * 100
    print(f"[{now}] Net: ${total:.2f} ({change:.2f}%)")
    if change >= 3:
        send(f"🎉 Portfolio up {change:.2f}% today!")

# --- Main ---
def main():
    init_db()
    send("🤖 Advanced trading bot started (multi-timeframe + shorting)")
    while True:
        try:
            trade()
        except Exception as e:
            send(f"⚠️ Bot error: {e}")
        time.sleep(300)

if __name__ == "__main__":
    main()
