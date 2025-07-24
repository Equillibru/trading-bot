import os
import time
import datetime
import json
import sqlite3
import requests
import statistics
from dotenv import load_dotenv
from binance.client import Client

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

client = Client(BINANCE_KEY, BINANCE_SECRET)

LIVE_MODE = False
START_BALANCE = 100.12493175
DB_PATH = "prices.db"
POSITION_FILE = "positions.json"
BALANCE_FILE = "balance.json"
TRADE_LOG_FILE = "trade_log.json"
VALID_PAIRS_FILE = "valid_pairs.json"
TRADING_PAIRS = []

all_pairs = [
    "BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "PEPEUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT",
    "PROMUSDT", "WBTCUSDT", "PAXGUSDT", "AWEUSDT", "REQUSDT",
    "BARUSDT", "ACMUSDT", "NEXOUSDT", "DEXEUSDT",
    "VOXELUSDT", "FIDAUSDT", "SYNUSDT", "ARDRUSDT", "JASMYUSDT",
    "ROSEUSDT", "FLOKIUSDT", "C98USDT", "BAKEUSDT", "MAGICUSDT"
]

def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except:
        pass

def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Failed to load {path}: {e} — resetting to default.")
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                symbol TEXT, timestamp TEXT, price REAL
            )
        """)

def save_price(symbol, price):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO prices (symbol, timestamp, price) VALUES (?, ?, ?)",
                     (symbol, now, price))
        conn.commit()

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

def get_cached_valid_pairs(all_symbols):
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    if os.path.exists(VALID_PAIRS_FILE):
        data = load_json(VALID_PAIRS_FILE, {})
        if data.get("last_updated") == today:
            return data.get("pairs", [])
    valid = []
    for symbol in all_symbols:
        try:
            if client.get_symbol_info(symbol):
                valid.append(symbol)
        except:
            pass
    save_json(VALID_PAIRS_FILE, {"last_updated": today, "pairs": valid})
    return valid

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

def log_trade(symbol, typ, qty, price):
    log = load_json(TRADE_LOG_FILE, [])
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    log.append({"symbol": symbol, "type": typ, "qty": qty, "price": price, "timestamp": timestamp})
    save_json(TRADE_LOG_FILE, log)

def trades_occurred_today():
    log = load_json(TRADE_LOG_FILE, [])
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    return any(t["timestamp"].startswith(today) for t in log)

# ... [imports and setup code remain unchanged]

def analyze_opportunity(symbol):
    klines = get_klines(symbol, Client.KLINE_INTERVAL_1HOUR, 168)
    if len(klines) < 168:
        print(f"⛔ Not enough data for {symbol}")
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

    print(f"🧠 Analyzing {symbol} | 1h: {one_hour:.2f}% | 3d: {three_day:.2f}% | 7d: {seven_day:.2f}% | Vol: {volatility:.4f}")

    if vol_recent <= vol_prev:
        print(f"📉 Skipped {symbol} — declining volume")
        return None
    if volatility > 0.02:
        print(f"⚠️ Skipped {symbol} — high volatility ({volatility:.4f})")
        return None

    headlines = get_news_headlines(symbol)
    bad_words = ["lawsuit", "ban", "hack", "crash", "regulation", "investigation"]
    good_words = ["surge", "rally", "gain", "partnership", "bullish", "upgrade", "adoption"]

    if any(any(bad in h.lower() for bad in bad_words) for h in headlines):
        print(f"🚫 Skipped {symbol} — negative news")
        return None
    if not any(any(good in h.lower() for good in good_words) for h in headlines):
        print(f"🟡 Skipped {symbol} — no strong positive news")
        return None

    print(f"✅ Signal found for {symbol} — {('BUY' if one_hour >= 1 else 'SHORT')}")
    if one_hour >= 1 and three_day >= 2 and seven_day >= 3:
        return "BUY", headlines
    elif one_hour <= -1 and three_day <= -2 and seven_day <= -3:
        return "SHORT", headlines
    return None

def trade():
    positions = load_json(POSITION_FILE, {})
    balance = load_json(BALANCE_FILE, {"usdt": START_BALANCE})
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')

    for symbol in TRADING_PAIRS:
        price = get_price(symbol)
        if not price:
            print(f"⚠️ Skipping {symbol} — price unavailable")
            continue
        print(f"🔍 Checking {symbol} at ${price:.2f}")
        save_price(symbol, price)

        result = analyze_opportunity(symbol)
        if not result:
            continue

        signal, headlines = result
        qty = round((balance["usdt"] * 0.5) / price, 6)
        if qty * price > balance["usdt"]:
            print(f"💸 Not enough balance to trade {symbol}")
            continue

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
            log_trade(symbol, signal, qty, price)
            news = "\n".join(f"📰 {h}" for h in headlines[:2]) if headlines else ""
            print(f"{tag} {qty} {symbol} at ${price:.2f}")
            send(f"{tag} {qty} {symbol} at ${price:.2f} — {now}\n{news}")

        elif symbol in positions:
            pos = positions[symbol]
            entry = pos["entry"]
            qty = pos["qty"]
            ptype = pos["type"]
            pnl = ((price - entry) / entry * 100) if ptype == "LONG" else ((entry - price) / entry * 100)
            print(f"📈 Open {ptype} {symbol} | Entry: {entry:.2f} → Now: {price:.2f} | PnL: {pnl:.2f}%")
            if pnl >= 1:
                action = "SELL" if ptype == "LONG" else "BUY"
                place_order(symbol, action, qty)
                balance["usdt"] += qty * price
                log_trade(symbol, f"CLOSE-{ptype}", qty, price)
                send(f"✅ CLOSE {ptype} {qty} {symbol} at ${price:.2f} — +{pnl:.2f}%")
                del positions[symbol]

    save_json(POSITION_FILE, positions)
    save_json(BALANCE_FILE, balance)

    invested = sum(p["qty"] * get_price(sym) for sym, p in positions.items())
    total = balance["usdt"] + invested
    change = ((total - START_BALANCE) / START_BALANCE) * 100
    print(f"[{now}] Balance: ${total:.2f} | Change: {change:.2f}%")

    if change >= 3:
        send(f"🎯 Daily goal reached: +{change:.2f}% — trades paused.")
        return

    if trades_occurred_today() and change >= 1:
        send(f"📈 Portfolio up {change:.2f}% today!")


def main():
    try:
        init_db()
        global TRADING_PAIRS
        TRADING_PAIRS = get_cached_valid_pairs(all_pairs)

        send("🤖 Trading bot started on Render (safe mode)")
        print("✅ Bot is running...")

        while True:
            try:
                trade()
            except Exception as e:
                print(f"ERROR in trade(): {e}")
                send(f"⚠️ Error in trade(): {e}")
            time.sleep(300)

    except Exception as e:
        print(f"❌ Fatal error in main(): {e}")
        send(f"🚨 Startup failed: {e}")

if __name__ == "__main__":
    main()
