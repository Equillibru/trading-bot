import os
import time
import datetime
import requests
import yfinance as yf
import pandas as pd
from dotenv import load_dotenv
from langchain_community.tools.yahoo_finance_news import YahooFinanceNewsTool

# Set user-agent
os.environ['USER_AGENT'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) TradingBot/1.0'


# Load env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
os.environ['USER_AGENT'] = 'TradingBot/1.0 (rk.ionescu@gmail.com'
os.environ['USER_AGENT'] = 'TradingBot/1.0'

# Initialize APIs
news_tool = YahooFinanceNewsTool()

# Binance crypto symbols (top 10, can be extended)
BINANCE_CRYPTO = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT"]

# Telegram alert
def send(msg):
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        )
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to send message: {e}")

# Fetch price history
def fetch_prices():
    data = {}

# Stocks (Yahoo Finance)
   for t in SP500_TICKERS:
        try:
        hist = yf.Ticker(t).history(period="1h", interval="5m")['Close'].dropna().tolist()
        data[t] = hist[-6:] if len(hist) >= 6 else hist
    except Exception as e:
        print(f"⚠️ Error fetching stock {t}: {e}")

# Crypto (Binance)
    for symbol in BINANCE_CRYPTO:
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=6"
            response = requests.get(url).json()
            prices = [float(kline[4]) for kline in response]  # closing prices
            data[symbol] = prices
        except Exception as e:
            print(f"⚠️ Error fetching crypto {symbol}: {e}")
    return data

# Analyze movement
def analyze(prices):
    if len(prices) < period + 1:
    return None
    change = ((prices[-1] - prices[0]) / prices[0]) * 100
    if change >= 1.0:
        return f"BUY (+{change:.2f}%)"
    elif change <= -1.0:
        return f"SELL ({change:.2f}%)"
    return None

# Scan all assets
def scan():
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    data = fetch_prices()
    for symbol, prices in data.items():
        signal = analyze(prices)
        if signal:
            try:
                news = news_tool.run(symbol[:10])[:3]  # Limit symbol length for crypto
                summary = "\n".join([f"- {n['title']}" for n in news]) if news else "No headlines"
            except Exception:
                summary = "📰 News unavailable"
            send(f"{signal} signal for {symbol} at {now}\n{summary}")

# Loop every 5 minutes
def main():
    send("🤖 Bot started (Binance + Yahoo | 5-min refresh)")
    while True:
        try:
            scan()
        except Exception as e:
            send(f"⚠️ Scan error: {e}")
        time.sleep(300)

if __name__ == "__main__":
    main()
