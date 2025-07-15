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

# Crypto tickers (Binance format)
BINANCE_CRYPTO = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT",
    "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT", "LINKUSDT", "DOGEUSDT"
]

# Get S&P 500 tickers
def get_sp500_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(url)
    return [t.replace('.', '-') for t in tables[0]["Symbol"].tolist()]

SP500_TICKERS = get_sp500_tickers()

# Telegram
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

# Finnhub daily and weekly prices
def get_finnhub_prices(symbol):
    try:
        now = int(time.time())
        start_of_today = now - (now % 86400)  # midnight UTC today
        seven_days_ago = now - 60 * 60 * 24 * 7

        # 5-minute interval for today
        intraday_url = "https://finnhub.io/api/v1/stock/candle"

        intraday = requests.get(intraday_url, params={
            "symbol": symbol,
            "resolution": "5",
            "from": start_of_today,
            "to": now,
            "token": FINNHUB_KEY
        }).json()

        weekly = requests.get(intraday_url, params={
            "symbol": symbol,
            "resolution": "D",
            "from": seven_days_ago,
            "to": now,
            "token": FINNHUB_KEY
        }).json()

        # use open price of the first 5-min candle today
        today_open = intraday['o'][0] if 'o' in intraday and intraday['o'] else None
        current_price = intraday['c'][-1] if 'c' in intraday and intraday['c'] else None
        week_ago_price = weekly['c'][0] if 'c' in weekly and weekly['c'] else None

        return current_price, today_open, week_ago_price
    except Exception as e:
        print(f"Finnhub intraday error for {symbol}: {e}")
        return None, None, None

# Binance crypto prices
def get_binance_prices(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit=7"
        r = requests.get(url).json()
        today_open = float(r[-1][1])  # Open of latest candle
        week_ago_close = float(r[0][4])  # Close 7 days ago
        current_price = float(r[-1][4])  # Close of today
        return current_price, today_open, week_ago_close
    except Exception as e:
        print(f"Binance error for {symbol}: {e}")
        return None, None, None

# Analyze both daily and 7-day trends
def analyze_trends(current, day_open, week_old):
    if not all([current, day_open, week_old]):
        return None
    day_change = ((current - day_open) / day_open) * 100
    week_change = ((current - week_old) / week_old) * 100
    print(f"📊 Daily: {day_change:.2f}%, Weekly: {week_change:.2f}%")
    if day_change >= 1 and week_change >= 3:
        return f"BUY (+{day_change:.2f}% today, +{week_change:.2f}% weekly)"
    elif day_change <= -1 and week_change <= -3:
        return f"SELL ({day_change:.2f}% today, {week_change:.2f}% weekly)"
    return None

# Main scanning logic
def scan():
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    positions = load_positions()

    # Stocks
    for symbol in SP500_TICKERS:
        current, day_open, week_old = get_finnhub_prices(symbol)
        signal = analyze_trends(current, day_open, week_old)
        if not current: continue
        entry = positions.get(symbol, {}).get("entry")

        if signal and "BUY" in signal and symbol not in positions:
            try:
                news = news_tool.run(symbol)[:3]
                summary = "\n".join([f"- {n['title']}" for n in news]) if news else "No headlines"
            except:
                summary = "News unavailable"
            send(f"{signal} signal for {symbol} at {now}\n{summary}")
            positions[symbol] = {"type": "BUY", "entry": current, "time": now}
            save_positions(positions)
        elif symbol in positions:
            change = ((current - entry) / entry) * 100
            if change >= 5:
                send(f"🎯 TAKE PROFIT: {symbol} is up {change:.2f}% since buy at {entry}")
                del positions[symbol]
            elif change <= -3:
                send(f"🛑 STOP LOSS: {symbol} is down {change:.2f}% since buy at {entry}")
                del positions[symbol]
            save_positions(positions)

    # Crypto
    for symbol in BINANCE_CRYPTO:
        current, day_open, week_old = get_binance_prices(symbol)
        signal = analyze_trends(current, day_open, week_old)
        if not current: continue
        entry = positions.get(symbol, {}).get("entry")

        if signal and "BUY" in signal and symbol not in positions:
            send(f"{signal} signal for {symbol} at {now}")
            positions[symbol] = {"type": "BUY", "entry": current, "time": now}
            save_positions(positions)
        elif symbol in positions:
            change = ((current - entry) / entry) * 100
            if change >= 5:
                send(f"🎯 TAKE PROFIT: {symbol} is up {change:.2f}% since buy at {entry}")
                del positions[symbol]
            elif change <= -3:
                send(f"🛑 STOP LOSS: {symbol} is down {change:.2f}% since buy at {entry}")
                del positions[symbol]
            save_positions(positions)

# Main loop
def main():
    send("🤖 Trend-based trading bot started!")
    while True:
        try:
            scan()
        except Exception as e:
            send(f"⚠️ Bot error: {e}")
        time.sleep(300)

if __name__ == "__main__":
    main()
