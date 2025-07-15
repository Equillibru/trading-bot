import os
import time
import datetime
import requests
import yfinance as yf
import pandas as pd
from dotenv import load_dotenv
from langchain_community.tools.yahoo_finance_news import YahooFinanceNewsTool

# Set user-agent for requests
os.environ['USER_AGENT'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) TradingBot/1.0'
print("✅ USER_AGENT is set to:", os.environ['USER_AGENT'])

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Initialize news tool
news_tool = YahooFinanceNewsTool()

# Get full list of S&P 500 tickers
def get_sp500_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(url)
    tickers = tables[0]["Symbol"].tolist()
    tickers = [t.replace('.', '-') for t in tickers]
    return tickers

SP500_TICKERS = get_sp500_tickers()

# Binance top crypto pairs
BINANCE_CRYPTO = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT",
    "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT", "LINKUSDT"
]

# Telegram alert sender
def send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"⚠️ Failed to send Telegram message: {e}")

# Fetch historical prices
def fetch_prices():
    data = {}

    # Fetch stock data
    for t in SP500_TICKERS:
        try:
            hist = yf.Ticker(t).history(period="1h", interval="5m")['Close'].dropna().tolist()
            data[t] = hist[-6:] if len(hist) >= 6 else hist
        except Exception as e:
            print(f"⚠️ Error fetching stock {t}: {e}")

    # Fetch crypto data from Binance
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
    if len(prices) < 2:
        return None
    change = ((prices[-1] - prices[0]) / prices[0]) * 100
    if change >= 1.0:
        return f"BUY (+{change:.2f}%)"
    elif change <= -1.0:
        return f"SELL ({change:.2f}%)"
    return None

# Scan all symbols and send alerts
def scan():
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    data = fetch_prices()
    for symbol, prices in data.items():
        signal = analyze(prices)
        if signal:
            try:
                news = news_tool.run(symbol[:10])[:3]
                summary = "\n".join([f"- {n['title']}" for n in news]) if news else "No headlines"
            except Exception:
                summary = "📰 News unavailable"
            send(f"{signal} signal for {symbol} at {now}\n{summary}")

# Main loop: refresh every 5 minutes
def main():
    send("🤖 Trading bot started (5-min scanner using Binance & Yahoo)")
    while True:
        try:
            scan()
        except Exception as e:
            send(f"⚠️ Error: {e}")
        time.sleep(300)

if __name__ == "__main__":
    main()
