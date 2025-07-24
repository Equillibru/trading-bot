import os
import time
import datetime
import json
import sqlite3
import requests
import statistics
from dotenv import load_dotenv
from binance.client import Client

# Load .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

client = Client(BINANCE_KEY, BINANCE_SECRET)

# Settings
LIVE_MODE = False
START_BUDGET = 100.0
DB_PATH = "prices.db"
POSITION_FILE = "positions.json"
BALANCE_FILE = "balance.json"
VALID_PAIRS_FILE = "valid_pairs.json"

# All symbols to validate (top 30 assets)
all_pairs = [
    "BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "PEPEUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT",
    "PROMUSDT", "WBTCUSDT", "PAXGUSDT", "AWEUSDT", "REQUSDT",
    "BARUSDT", "ACMUSDT", "NEXOUSDT", "DEXEUSDT",
    "VOXELUSDT", "FIDAUSDT", "SYNUSDT", "ARDRUSDT", "JASMYUSDT",
    "ROSEUSDT", "FLOKIUSDT", "C98USDT", "BAKEUSDT", "MAGICUSDT"
]

# Telegram
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except:
        pass

# JSON file handling
def load_json(path, default):
    return json.load(open(path)) if os.path.exists(path) else default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# SQLite price DB
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS prices (
            symbol TEXT, timestamp TEXT, price REAL
        )""")

def save_price(symbol, price):
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO prices (symbol, timestamp, price) VALUES (?, ?, ?)",
                     (symbol, now, price))
        conn.commit()

# Binance market data
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

# NewsAPI
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

# Cached valid trading pairs
def get_cached_valid_pairs(all_symbols):
    today = datetime.datetime.utcnow().date().isoformat()
    if os.path.exists(VALID_PAIRS_FILE):
        with open(VALID_PAIRS_FILE, "r") as f:
            data = json.load(f)
            if data.get("last_updated") == today:
                print("✅ Using cached valid pairs.")
                return data.get("pairs", [])
    print("🔁 Validating symbols...")
    valid = []
    for symbol in all_symbols:
        try:
            if client.get_symbol_info(symbol):
                valid.append(symbol)
        except:
            pass
    with open(VALID_PAIRS_FILE, "w") as f:
        json.dump({"last_updated": today, "pairs": valid}, f, indent=2)
    return valid

# Simulated or real trade
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

# Strategy logic
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

    # Trends
    one_hour = ((now - hour_ago) / hour_ago) * 100
    three_day = ((now - three_days_ago) / three_days_ago) * 100
    seven_day = ((now - week_ago) / week_ago) * 100

    # Filters
    vol_recent = sum(volumes[-6:])
    vol_prev = sum(volumes[-12:-6])
    volatility = statistics.stdev(closes[-24:]) / now

    if vol_recent <= vol_prev or volatility > 0.02:
        return None

    # News filters
    headlines = get_news_headlines(symbol)
    bad_words = ["lawsuit", "ban", "hack", "crash", "regulation", "investigation"]
    positive_words = ["surge", "rally", "gain", "partnership", "bullish", "upgrade", "adoption"]

    if any(any(bad in h.lower() for bad in bad_words) for h in headlines):
        print(f"❌ Negative news for {symbol}")
        return None

    if not any(any(pos in h.lower() for pos in positive_words) for h in headlines):
        print(f"⚠️ No positive news for {symbol}")
        return None

    # Final decision
    if one_hour >= 1 and three_day >= 2 and seven_day >= 3:
        return "BUY", headlines
    elif one_hour <= -1 and three_day <= -2 and seven_day <= -3:
        return "SHORT", headlines
    return None

# Trading loop
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

        signal, headlines = signal_data
        qty = round((balance["usdt"] * 0.5) / price, 6)
        if qty * price > balance["usdt"]:
            continue

        # Entry
        if symbol not in positions:
            if signal == "BUY":
                place_order(symbol, "BUY", qty)
                positions[symbol] = {"type": "LONG", "qty": qty, "entry": price}
                balance["usdt"] -= qty * price
                tag = "🟢 BUY"
            elif signal == "SHORT":
                place_order(symbol, "SELL", qty)
                positions[symbol] = {"type": "SHORT", "qty": qty, "entry": price}
                balance["usdt"] -= qty * price
                tag = "🔻 SHORT"

            news_block = "\n".join(f"📰 {h}" for h in headlines[:2]) if headlines else ""
            send(f"{tag} {qty} {symbol} at ${price:.2f} — {now}\n{news_block}")

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
                send(f"✅ CLOSE {pos_type} {qty} {symbol} at ${price:.2f} — +{pnl:.2f}%")
                del positions[symbol]

    save_json(POSITION_FILE, positions)
    save_json(BALANCE_FILE, balance)

    invested = sum(p["qty"] * get_price(sym) for sym, p in positions.items())
    total = balance["usdt"] + invested
    change = ((total - START_BUDGET) / START_BUDGET) * 100
    print(f"[{now}] Net: ${total:.2f} ({change:.2f}%)")
    if change >= 3:
        send(f"🎉 Portfolio up {change:.2f}%")

# Main loop
def main():
    init_db()
    global TRADING_PAIRS
    TRADING_PAIRS = get_cached_valid_pairs(all_pairs)
    send("🤖 Bot started with smart news + trend filters.")
    while True:
        try:
            trade()
        except Exception as e:
            send(f"⚠️ Error: {e}")
        time.sleep(300)

if __name__ == "__main__":
    main()
