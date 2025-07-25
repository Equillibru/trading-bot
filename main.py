import os
import time
import datetime
import json
import sqlite3
import requests
from dotenv import load_dotenv
from binance.client import Client
from textblob import TextBlob
import logging

# === SETUP ===
load_dotenv()

# Load environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

client = Client(BINANCE_KEY, BINANCE_SECRET)

# Configurable parameters
config = {
    "LIVE_MODE": False,
    "START_BALANCE": 100.12493175,
    "DB_PATH": "prices.db",
    "POSITION_FILE": "positions.json",
    "BALANCE_FILE": "balance.json",
    "TRADE_LOG_FILE": "trade_log.json",
    "PROFIT_THRESHOLD": 0.5,
    "TRADING_PAIRS": [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
        "ADAUSDT", "DOGEUSDT", "LINKUSDT", "MATICUSDT", "DOTUSDT"
    ],
    "BAD_WORDS": ["lawsuit", "ban", "hack", "crash", "regulation", "investigation"],
    "GOOD_WORDS": ["surge", "rally", "gain", "partnership", "bullish", "upgrade", "adoption"]
}

# === LOGGING ===
logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def log_error(message):
    logging.error(message)
    print(message)

def log_info(message):
    logging.info(message)
    print(message)

# === TELEGRAM NOTIFICATIONS ===
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        log_error(f"Telegram error: {e}")

# === DATABASE FUNCTIONS ===
def init_db():
    with sqlite3.connect(config["DB_PATH"]) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                symbol TEXT, timestamp TEXT, price REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                symbol TEXT, type TEXT, qty REAL, price REAL, timestamp TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                timestamp TEXT, balance REAL
            )
        """)

def save_price(symbol, price):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with sqlite3.connect(config["DB_PATH"]) as conn:
            conn.execute("INSERT INTO prices (symbol, timestamp, price) VALUES (?, ?, ?)",
                         (symbol, now, price))
            conn.commit()
        log_info(f"💾 Saved {symbol} at ${price:.2f}")
    except Exception as e:
        log_error(f"❌ DB save error for {symbol}: {e}")

# === HELPER FUNCTIONS ===
def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        log_error(f"⚠️ Failed to load {path}: {e} — resetting.")
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def get_price(symbol):
    try:
        return float(client.get_symbol_ticker(symbol=symbol)['price'])
    except Exception as e:
        log_error(f"⚠️ Error fetching price for {symbol}: {e}")
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
        log_error(f"❌ NewsAPI error for {symbol}: {e}")
        return []

def analyze_sentiment(headlines):
    sentiment_score = 0
    for headline in headlines:
        sentiment = TextBlob(headline).sentiment.polarity
        sentiment_score += sentiment
    return sentiment_score

def log_trade(symbol, typ, qty, price):
    log = load_json(config["TRADE_LOG_FILE"], [])
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    log.append({"symbol": symbol, "type": typ, "qty": qty, "price": price, "timestamp": timestamp})
    save_json(config["TRADE_LOG_FILE"], log)

# === TRADING LOGIC ===
def trade():
    positions = load_json(POSITION_FILE, {})
    balance = load_json(BALANCE_FILE, {"usdt": START_BALANCE})
    starting_balance = balance["usdt"]  # Store the starting balance
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
            continue
        if not headlines:
            print(f"⚠️ No news headlines for {symbol}")
            continue

        qty = round((balance["usdt"] * 0.5) / price, 6)

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

    save_json(POSITION_FILE, positions)
    save_json(BALANCE_FILE, balance)

    invested = sum(p["qty"] * get_price(sym) for sym, p in positions.items())
    ending_balance = balance["usdt"] + invested  # Calculate the ending balance
    profit_percentage = ((ending_balance - starting_balance) / starting_balance) * 100

    # Send Telegram message with starting and ending balance
    send(f"💰 Starting Balance: ${starting_balance:.2f}\n💰 Ending Balance: ${ending_balance:.2f}\n📈 Profit/Loss: {profit_percentage:.2f}%")

    print(f"[{now}] Net balance: ${ending_balance:.2f}")

# === MAIN FUNCTION ===
def main():
    try:
        init_db()
        log_info("🤖 Trading bot started")
        send("🤖 Trading bot running with sentiment analysis")
        print(f"Current balance: ${balance['usdt']:.2f}") #Verify trade balance

        while True:
            try:
                trade()
            except Exception as e:
                log_error(f"ERROR in trade(): {e}")
                send(f"⚠️ Error in trade(): {e}")
            time.sleep(300)
    except Exception as e:
        log_error(f"❌ Startup failed: {e}")
        send(f"🚨 Bot failed to start: {e}")

if __name__ == "__main__":
    main()
