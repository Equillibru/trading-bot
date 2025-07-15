import os
import time
import datetime
import requests
import pandas as pd
import json
from dotenv import load_dotenv
from langchain_community.tools.yahoo_finance_news import YahooFinanceNewsTool

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")

# Constants
POSITION_FILE = "positions.json"
os.environ['USER_AGENT'] = 'Mozilla/5.0 (TradingBot)'

# News tool
news_tool = YahooFinanceNewsTool()

# Binance crypto pairs
BINANCE_CRYPTO = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT",
    "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT", "LINKUSDT"
]

# Get S&P 500 tickers
def get_sp500_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(url)
    return [t.replace('.', '-') for t in tables[0]["Symbol"].tolist()]

SP500_TICKERS = get_sp500_tickers()

# Telegram sender
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"Telegram send error: {e}")

# Load/save positions
def load_positions():
    if os.path.exists(POSITION_FILE):
        with open(POSITION_FILE, "r") as f:
            return json.load(f)
    return {}

def save_positions(data):
    with open(POSITION_FILE, "w") as f:
        json.dump(data, f, indent=2)

# Get stock prices from Finnhub
def get_stock_prices_finnhub(symbol):
    try:
        url = "https://finnhub.io/api/v1/stock/candle"
        params = {
            "symbol": symbol,
            "resolution": "5",
            "count": 6,
            "token": FINNHUB_KEY
        }
        r = requests.get(url, params=params).json()
        if r.get("s") == "ok":
            return r["c"]
    except Exception as e:
        print(f"Finnhub error for {symbol}: {e}")
    return []

# Get crypto prices from Binance
def get_crypto_prices_binance(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=6"
        r = requests.get(url).json()
        return [float(kline[4]) for kline in r]
    except Exception as e:
        print(f"Binance error for {symbol}: {e}")
        return []

# Analyze movement
def analyze(prices):
    if len(prices) < 2:
        return None
    change = ((prices[-1] - prices[0]) / prices[0]) * 100
    if change >= 1.0:
        return f"BUY (+{change:.2f}%)"
    elif change <= -1.0:
        return f"SELL ({change:.2f}%)"
    return None

# Main scan
def scan():
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    positions = load_positions()

    # STOCKS
    for symbol in SP500_TICKERS:
        prices = get_stock_prices_finnhub(symbol)
        if not prices:
            continue
        signal = analyze(prices)
        current = prices[-1]
        entry = positions.get(symbol, {}).get("entry")

        if signal and "BUY" in signal and symbol not in positions:
            send(f"{signal} signal for {symbol} at {now}")
            positions[symbol] = {"type": "BUY", "entry": current, "time": now}
            save_positions(positions)
        elif symbol in positions:
            change = ((current - entry) / entry) * 100
            if change >= 5:
                send(f"🎯 TAKE PROFIT: {symbol} is up {change:.2f}% since entry at {entry}")
                del positions[symbol]
                save_positions(positions)
            elif change <= -3:
                send(f"🛑 STOP LOSS: {symbol} is down {change:.2f}% since entry at {entry}")
                del positions[symbol]
                save_positions(positions)

    # CRYPTO
    for symbol in BINANCE_CRYPTO:
        prices = get_crypto_prices_binance(symbol)
        if not prices:
            continue
        signal = analyze(prices)
        current = prices[-1]
        entry = positions.get(symbol, {}).get("entry")

        if signal and "BUY" in signal and symbol not in positions:
            send(f"{signal} signal for {symbol} at {now}")
            positions[symbol] = {"type": "BUY", "entry": current, "time": now}
            save_positions(positions)
        elif symbol in positions:
            change = ((current - entry) / entry) * 100
            if change >= 5:
                send(f"🎯 TAKE PROFIT: {symbol} is up {change:.2f}% since entry at {entry}")
                del positions[symbol]
                save_positions(positions)
            elif change <= -3:
                send(f"🛑 STOP LOSS: {symbol} is down {change:.2f}% since entry at {entry}")
                del positions[symbol]
                save_positions(positions)

# Main loop
def main():
    send("🤖 Trading bot started with trade tracking.")
    while True:
        try:
            scan()
        except Exception as e:
            send(f"⚠️ Bot error: {e}")
        time.sleep(300)

if __name__ == "__main__":
    main()
