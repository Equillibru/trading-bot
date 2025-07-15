import os
import time
import datetime
import requests
import pandas as pd
import json

POSITION_FILE = "positions.json"

def load_positions():
    if os.path.exists(POSITION_FILE):
        with open(POSITION_FILE, "r") as f:
            return json.load(f)
    return {}

def save_positions(data):
    with open(POSITION_FILE, "w") as f:
        json.dump(data, f, indent=2)
        
from dotenv import load_dotenv
from langchain_community.tools.yahoo_finance_news import YahooFinanceNewsTool

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")

# Set USER_AGENT
os.environ['USER_AGENT'] = 'Mozilla/5.0 (TradingBot)'

# Initialize news tool
news_tool = YahooFinanceNewsTool()

# Binance crypto pairs (top 10)
BINANCE_CRYPTO = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT",
    "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT", "LINKUSDT"
]

# S&P 500 Tickers from Wikipedia (symbols only)
def get_sp500_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(url)
    tickers = tables[0]["Symbol"].tolist()
    return tickers

SP500_TICKERS = get_sp500_tickers()

# Send Telegram alert
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"Telegram send error: {e}")

# Fetch stock prices using Finnhub
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

# Fetch crypto prices using Binance
def get_crypto_prices_binance(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=6"
        r = requests.get(url).json()
        return [float(kline[4]) for kline in r]  # closing prices
    except Exception as e:
        print(f"Binance error for {symbol}: {e}")
        return []

# Analyze % change
def analyze(prices):
    if len(prices) < 2:
        return None
    change = ((prices[-1] - prices[0]) / prices[0]) * 100
    if change >= 0.5:
        return f"BUY (+{change:.2f}%)"
    elif change <= -0.5:
        return f"SELL ({change:.2f}%)"
    return None

# Main scan function
def scan():
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

# Scan stocks
for symbol in SP500_TICKERS:
    prices = get_stock_prices_finnhub(symbol)
    signal = analyze(prices)
    current_price = prices[-1] if prices else None

    # Entry signal
    if signal and signal.startswith("BUY") and symbol not in positions:
        send(f"{signal} signal for {symbol} at {now}")
        positions[symbol] = {"type": "BUY", "entry": current_price, "time": now}
        save_positions(positions)

    # Exit signal (take profit / stop loss)
    elif symbol in positions:
        entry = positions[symbol]['entry']
        change = ((current_price - entry) / entry) * 100 if entry else 0
        if change >= 5:
            send(f"🎯 TAKE PROFIT: {symbol} is up {change:.2f}% since buy at {entry}")
            del positions[symbol]
        elif change <= -3:
            send(f"🛑 STOP LOSS: {symbol} is down {change:.2f}% since buy at {entry}")
            del positions[symbol]
        save_positions(positions)

    # Scan crypto
    for symbol in BINANCE_CRYPTO:
        prices = get_crypto_prices_binance(symbol)
        signal = analyze(prices)
        if signal:
            send(f"{signal} signal for {symbol} at {now}")

# Bot loop
def main():
    send("🤖 Trading bot started (Finnhub + Binance)")
    while True:
        try:
            scan()
        except Exception as e:
            send(f"⚠️ Bot error: {e}")
        time.sleep(300)  # wait 5 min

if __name__ == "__main__":
    main()
