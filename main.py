import os
import time
import datetime
import statistics
import requests
import yfinance as yf
import pandas as pd
from pycoingecko import CoinGeckoAPI
from dotenv import load_dotenv
from langchain_community.tools.yahoo_finance_news import YahooFinanceNewsTool

# Load env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("7668069380:AAGiZHHRPCzwPz604jmXm82cAjszVqVmFtA")
TELEGRAM_CHAT_ID = os.getenv("6574517543")

# Initialize APIs
cg = CoinGeckoAPI()
news_tool = YahooFinanceNewsTool()

SP500_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]  # top 5 S&P 500 stocks
CRYPTO_TOP25 = [c['id'] for c in cg.coins_markets(vs_currency='usd', per_page=25, page=1)]

def get_sp500_tickers():
    table = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    return table[0]['Symbol'].tolist()

SP500_TICKERS = get_sp500_tickers()
def send(msg):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    )

def fetch_prices():
    data = {}
    for t in SP500_TICKERS:
        hist = yf.Ticker(t).history(period="2d", interval="1h")['Close'].tolist()
        data[t] = hist[-30:] if len(hist)>=30 else []
    for c in CRYPTO_TOP25:
        prices = cg.get_coin_market_chart_by_id(id=c, vs_currency='usd', days=1)['prices']
        data[c] = [p[1] for p in prices[-30:]]
    return data

def analyze(prices):
    if len(prices) < 20: return None
    sma5 = sum(prices[-5:])/5
    sma20 = sum(prices[-20:])/20
    rsi = calc_rsi(prices)
    std = statistics.stdev(prices[-20:])
    width = std/sma20
    if sma5> sma20 and rsi<35 and width<0.02: return "BUY"
    if sma5< sma20 and rsi>65: return "SELL"
    return None

def calc_rsi(prices, period=14):
    gains = [max(prices[i+1]-prices[i],0) for i in range(-period-1, -1)]
    losses = [abs(min(prices[i+1]-prices[i],0)) for i in range(-period-1, -1)]
    ag, al = sum(gains)/period, sum(losses)/period
    return 100 - 100/(1+ag/al) if al else 100

def scan():
    data = fetch_prices()
    for symbol, prices in data.items():
        act = analyze(prices)
        if act:
            news = news_tool.run(symbol)[:3]
            summary = "\n".join([f"- {n['title']}" for n in news])
            send(f"{act} {symbol}\n{summary}")

def main():
    send("Bot started")
    while True:
        try:
            scan()
        except Exception as e:
            send(f"Error: {e}")
        time.sleep(60*30)

if __name__ == "__main__":
    main()
