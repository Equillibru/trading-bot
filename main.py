import os
import time
import datetime
import sqlite3
import requests
import logging
from dotenv import load_dotenv
from binance.client import Client

# === Environment Setup ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY")

client = Client(BINANCE_KEY, BINANCE_SECRET)

# === Logging ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# === Config ===
CONFIG = {
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "trade_fraction": 0.2,
    "profit_threshold": 0.5,  # percent
    "stop_loss_threshold": -2.0,
    "loop_interval": 300,
    "live_mode": True,
    "starting_balance": 100.0,
    "db_path": "trading.db"
}

positions = {}
balance = {"usdt": CONFIG["starting_balance"]}
trading_paused = False

# === Telegram ===
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        logging.error("Telegram error", exc_info=True)

# === Binance Helpers ===
def get_price(symbol):
    try:
        return float(client.get_symbol_ticker(symbol=symbol)["price"])
    except:
        return None

def place_order(symbol, side, qty):
    if CONFIG["live_mode"]:
        return client.create_order(symbol=symbol, side=side.upper(), type="MARKET", quantity=qty)
    else:
        logging.info(f"[SIMULATED] {side} {qty} {symbol}")
        return {"simulated": True}

# === PnL Tracker ===
def get_current_total():
    total = balance["usdt"]
    for symbol, pos in positions.items():
        price = get_price(symbol)
        if price:
            total += pos["qty"] * price
    return total

# === Trade Logic ===
def trade():
    global trading_paused
    if trading_paused:
        return

    total_value = get_current_total()
    pnl = ((total_value - CONFIG["starting_balance"]) / CONFIG["starting_balance"]) * 100

    if pnl >= 3.0:
        send(f"🎯 Daily profit target hit: +{pnl:.2f}% — trading paused.")
        logging.info("✅ Trading paused due to profit target.")
        trading_paused = True
        return

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    for symbol in CONFIG["symbols"]:
        price = get_price(symbol)
        if not price:
            continue

        qty = round((balance["usdt"] * CONFIG["trade_fraction"]) / price, 6)

        if symbol not in positions:
            if qty * price > balance["usdt"]:
                continue
            place_order(symbol, "BUY", qty)
            positions[symbol] = {"qty": qty, "entry": price}
            balance["usdt"] -= qty * price
            send(f"🟢 BUY {qty} {symbol} at ${price:.2f} — ${qty*price:.2f}")
            logging.info(f"BUY {qty} {symbol} at ${price:.2f}")

        else:
            pos = positions[symbol]
            entry = pos["entry"]
            qty = pos["qty"]
            change = ((price - entry) / entry) * 100
            profit = (price - entry) * qty

            if change >= CONFIG["profit_threshold"] or change <= CONFIG["stop_loss_threshold"]:
                place_order(symbol, "SELL", qty)
                balance["usdt"] += qty * price
                del positions[symbol]
                send(f"🔻 CLOSE {symbol} at ${price:.2f} | PnL: {profit:.2f} USD ({change:.2f}%)")
                logging.info(f"CLOSE {symbol} | PnL: {profit:.2f} USD")

# === Main Loop ===
def main():
    send("🤖 Bot started with trade cap and daily PnL tracking")
    while True:
        try:
            trade()
        except Exception as e:
            logging.error("Error in trade loop", exc_info=True)
            send(f"⚠️ Error: {e}")
        time.sleep(CONFIG["loop_interval"])

if __name__ == "__main__":
    main()
