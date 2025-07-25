import os
import time
import datetime
import json
import sqlite3
import requests
import logging
import csv
from dotenv import load_dotenv
from binance.client import Client
from textblob import TextBlob

# === Load environment ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

# === Setup ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
client = Client(BINANCE_KEY, BINANCE_SECRET)

# === Config ===
CONFIG = {
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
    "trade_fraction": 0.5,
    "profit_threshold": 0.5,
    "stop_loss_threshold": -2.0,
    "sentiment_threshold": 0.0,
    "loop_interval": 300,
    "live_mode": True,
    "db_path": "trading.db",
    "csv_log": "trades.csv"
}

# === DB Init ===
def init_db():
    with sqlite3.connect(CONFIG["db_path"]) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            symbol TEXT, timestamp TEXT, price REAL
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
            symbol TEXT, type TEXT, qty REAL,
            entry_price REAL, exit_price REAL,
            profit REAL, timestamp TEXT
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS balances (
            timestamp TEXT, usdt REAL
        )""")

# === Telegram ===
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown"
        })
    except Exception as e:
        logging.error("Telegram error", exc_info=True)

# === Utilities ===
def get_price(symbol):
    try:
        return float(client.get_symbol_ticker(symbol=symbol)['price'])
    except Exception as e:
        logging.warning(f"Price unavailable for {symbol}: {e}")
        return None

def place_order(symbol, side, qty):
    try:
        if CONFIG["live_mode"]:
            return client.create_order(
                symbol=symbol,
                side=side.upper(),
                type="MARKET",
                quantity=qty
            )
        else:
            logging.info(f"[SIMULATED] {side} {qty} {symbol}")
            return {"simulated": True}
    except Exception as e:
        logging.error(f"Order failed for {symbol}: {e}")
        return None

def save_price(symbol, price):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with sqlite3.connect(CONFIG["db_path"]) as conn:
            conn.execute("INSERT INTO prices (symbol, timestamp, price) VALUES (?, ?, ?)",
                         (symbol, now, price))
    except Exception as e:
        logging.error("Failed to save price", exc_info=True)

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
        logging.error(f"News fetch failed for {symbol}: {e}")
        return []

def get_sentiment_score(headlines):
    scores = []
    for h in headlines:
        print(f"📰 Headline: {h}")
        blob = TextBlob(h)
        score = blob.sentiment.polarity
        print(f"📊 Sentiment Score: {score:.2f}")
        scores.append(score)
    return sum(scores) / len(scores) if scores else 0

def get_trend(symbol):
    try:
        klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=168)
        closes = [float(k[4]) for k in klines]
        current = closes[-1]
        hour_ago = closes[-2]
        day_ago = closes[-24]
        week_ago = closes[0]
        return {
            "1h": (current - hour_ago) / hour_ago * 100,
            "1d": (current - day_ago) / day_ago * 100,
            "7d": (current - week_ago) / week_ago * 100,
        }
    except Exception as e:
        logging.warning(f"Trend fetch failed for {symbol}: {e}")
        return {"1h": 0, "1d": 0, "7d": 0}

def log_to_csv(symbol, typ, qty, price, pnl):
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with open(CONFIG["csv_log"], "a", newline='') as f:
        writer = csv.writer(f)
        writer.writerow([now, symbol, typ, qty, price, pnl])

# === Trading Logic ===
positions = {}
balance = {"usdt": 100.0}

def trade():
    global positions, balance
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')

    for symbol in CONFIG["symbols"]:
        price = get_price(symbol)
        if not price:
            continue

        save_price(symbol, price)
        trend = get_trend(symbol)
        print(f"📊 Trend {symbol}: 1h={trend['1h']:.2f}%, 1d={trend['1d']:.2f}%, 7d={trend['7d']:.2f}%")

        headlines = get_news_headlines(symbol)
        sentiment_score = get_sentiment_score(headlines)

        if sentiment_score < CONFIG["sentiment_threshold"]:
            logging.info(f"{symbol} skipped: low sentiment ({sentiment_score:.2f})")
            continue

        qty = round((balance["usdt"] * CONFIG["trade_fraction"]) / price, 6)
        if qty * price > balance["usdt"]:
            logging.info(f"{symbol} skipped: insufficient balance")
            continue

        # BUY
        if symbol not in positions:
            order = place_order(symbol, "BUY", qty)
            if order:
                positions[symbol] = {"qty": qty, "entry": price}
                balance["usdt"] -= qty * price
                with sqlite3.connect(CONFIG["db_path"]) as conn:
                    conn.execute("INSERT INTO balances VALUES (?, ?)",
                                 (datetime.datetime.now(datetime.timezone.utc).isoformat(), balance["usdt"]))
                send(f"*BUY* `{symbol}` at `${price:.2f}`\nQty: `{qty}`\nCost: `${qty * price:.2f}`")
                log_to_csv(symbol, "BUY", qty, price, 0)
                logging.info(f"Bought {qty} {symbol} at {price:.2f}")
        else:
            entry = positions[symbol]["entry"]
            qty = positions[symbol]["qty"]
            pnl = ((price - entry) / entry) * 100
            profit = (price - entry) * qty

            if pnl >= CONFIG["profit_threshold"] or pnl <= CONFIG["stop_loss_threshold"]:
                order = place_order(symbol, "SELL", qty)
                if order:
                    balance["usdt"] += qty * price
                    with sqlite3.connect(CONFIG["db_path"]) as conn:
                        conn.execute("INSERT INTO trades (symbol, type, qty, entry_price, exit_price, profit, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                     (symbol, "CLOSE-LONG", qty, entry, price, profit,
                                      datetime.datetime.now(datetime.timezone.utc).isoformat()))
                        conn.execute("INSERT INTO balances VALUES (?, ?)",
                                     (datetime.datetime.now(datetime.timezone.utc).isoformat(), balance["usdt"]))
                    send(f"*CLOSE* `{symbol}` at `${price:.2f}`\nProfit: `${profit:.2f}` ({pnl:.2f}%)")
                    log_to_csv(symbol, "CLOSE", qty, price, pnl)
                    logging.info(f"Closed {symbol} at {price:.2f} | PnL: {pnl:.2f}%")
                    del positions[symbol]

    logging.info(f"[{now}] Balance: ${balance['usdt']:.2f}")

# === Main Loop ===
def main():
    init_db()
    send("🤖 Bot started with trend tracking, stop-loss, and dashboard logging.")
    logging.info("Bot running")

    while True:
        try:
            trade()
        except Exception as e:
            logging.error("Trade loop failed", exc_info=True)
            send(f"❌ Error: {e}")
        time.sleep(CONFIG["loop_interval"])

if __name__ == "__main__":
    main()
