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
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

client = Client(BINANCE_KEY, BINANCE_SECRET)
TRADING_PAIRS = filter_valid_pairs(TRADING_PAIRS)

def main():
    init_db()
    global TRADING_PAIRS
    TRADING_PAIRS = filter_valid_pairs(TRADING_PAIRS)
    send("🤖 Trading bot started with filtered Binance pairs")
    ...

# Config
LIVE_MODE = False
START_BUDGET = 100.0
all_pairs = [
    "BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "PEPEUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT",
    "PROMUSDT", "WBTCUSDT", "PAXGUSDT", "AWEUSDT", "REQUSDT",
    "BARUSDT", "ACMUSDT", "NEXOUSDT", "DEXEUSDT",
    "VOXELUSDT", "FIDAUSDT", "SYNUSDT", "ARDRUSDT", "JASMYUSDT",
    "ROSEUSDT", "FLOKIUSDT", "C98USDT", "BAKEUSDT", "MAGICUSDT"
]
TRADING_PAIRS = filter_valid_pairs(all_pairs)
DB_PATH = "prices.db"
POSITION_FILE = "positions.json"
BALANCE_FILE = "balance.json"

# Telegram
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except:
        pass

# JSON I/O
def load_json(path, default):
    return json.load(open(path)) if os.path.exists(path) else default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# DB setup
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

# Price & kline data
def get_price(symbol):
    try:
        return float(client.get_symbol_ticker(symbol=symbol)['price'])
    except:
        return None

def get_klines(symbol, interval, limit):
    try:
        return client.get_klines(symbol=symbol, interval=interval, limit=limit)
    except:
        return []

# NewsAPI integration
def get_news_headlines(symbol, limit=5):
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": symbol.replace("USDT", ""),
            "apiKey": NEWSAPI_KEY,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": limit
        }
        r = requests.get(url, params=params).json()
        return [a["title"] for a in r.get("articles", []) if "title" in a]
    except:
        return []

# Trade logic
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

# Strategy
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

    one_hour = ((now - hour_ago) / hour_ago) * 100
    three_day = ((now - three_days_ago) / three_days_ago) * 100
    seven_day = ((now - week_ago) / week_ago) * 100

    vol_recent = sum(volumes[-6:])
    vol_prev = sum(volumes[-12:-6])
    volatility = statistics.stdev(closes[-24:]) / now

    if vol_recent <= vol_prev or volatility > 0.02:
        return None

    headlines = get_news_headlines(symbol)
    bad_words = ["lawsuit", "ban", "crash", "hack", "fine", "delisting"]
    if any(any(bad in h.lower() for bad in bad_words) for h in headlines):
        print(f"❌ Skipping {symbol} due to negative news")
        return None

    if one_hour >= 1 and three_day >= 2 and seven_day >= 3:
        return "BUY", headlines
    elif one_hour <= -1 and three_day <= -2 and seven_day <= -3:
        return "SHORT", headlines
    return None

# Main trade loop
def trade():
    positions = load_json(POSITION_FILE, {})
    balance = load_json(BALANCE_FILE, {"usdt": START_BUDGET})
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    for symbol in TRADING_PAIRS:
        price = get_price(symbol)
        if not price:
            continue
        save_price(symbol, price)

        signal_data = analyze_opportunity(symbol)
        if not signal_data:
            continue
        action, headlines = signal_data

        # Entry
        if symbol not in positions:
            usdt_available = balance["usdt"]
            allocation = usdt_available * 0.5
            qty = round(allocation / price, 6)
            if qty * price > usdt_available:
                continue

            if action == "BUY":
                place_order(symbol, "BUY", qty)
                positions[symbol] = {"type": "LONG", "qty": qty, "entry": price}
                balance["usdt"] -= qty * price
                tag = "🟢 BUY"
            elif action == "SHORT":
                place_order(symbol, "SELL", qty)
                positions[symbol] = {"type": "SHORT", "qty": qty, "entry": price}
                balance["usdt"] -= qty * price
                tag = "🔻 SHORT"

            news_text = "\n".join(f"📰 {h}" for h in headlines[:2]) if headlines else ""
            send(f"{tag} {qty} {symbol} at ${price:.2f} — {now}\n{news_text}")

        # Exit
        elif symbol in positions:
            entry = positions[symbol]["entry"]
            qty = positions[symbol]["qty"]
            pos_type = positions[symbol]["type"]

            pnl = ((price - entry) / entry * 100) if pos_type == "LONG" else ((entry - price) / entry * 100)
            if pnl >= 1:
                side = "SELL" if pos_type == "LONG" else "BUY"
                place_order(symbol, side, qty)
                balance["usdt"] += qty * price
                send(f"✅ CLOSED {pos_type} {qty} {symbol} at ${price:.2f} — P/L: {pnl:.2f}%")
                del positions[symbol]

    save_json(POSITION_FILE, positions)
    save_json(BALANCE_FILE, balance)

    invested = sum(p["qty"] * get_price(sym) for sym, p in positions.items())
    total = balance["usdt"] + invested
    change = ((total - START_BUDGET) / START_BUDGET) * 100
    print(f"[{now}] Total: ${total:.2f} ({change:.2f}%)")
    if change >= 3:
        send(f"🎉 Portfolio up {change:.2f}%")

# Main loop
def main():
    init_db()
    send("🤖 Bot with NewsAPI & Smart Trends started")
    while True:
        try:
            trade()
        except Exception as e:
            send(f"⚠️ Bot error: {e}")
        time.sleep(300)

if __name__ == "__main__":
    main()
