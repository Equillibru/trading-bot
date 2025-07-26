# Trading Bot

A simple cryptocurrency trading bot that uses the Binance API and filters trades based on recent news headlines.

## Setup

1. Clone the repository.
2. Install dependencies:

```bash
python -m pip install -r requirements.txt
```
3. Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
# then edit .env
```

Required variables:

- `TELEGRAM_TOKEN` – Telegram bot token used for notifications.
- `TELEGRAM_CHAT_ID` – Chat ID to receive bot messages.
- `BINANCE_API_KEY` – Binance API key.
- `BINANCE_SECRET_KEY` – Binance secret key.
- `FINNHUB_KEY` – Finnhub API key (not currently used).
- `NEWSAPI_KEY` – NewsAPI key for fetching headlines.

## Usage

Run the bot with:

```bash
python main.py
```

Set `LIVE_MODE = True` in `main.py` to place real orders. Leave it `False` to simulate trades.
