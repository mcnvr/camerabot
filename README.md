# resellbot — Canon restock monitor

Polls a Canon product page and sends a Telegram alert when it restocks.

## Setup
1. Create a Telegram bot via @BotFather → get `TELEGRAM_BOT_TOKEN`.
2. Get your numeric chat id (message the bot, then check `https://api.telegram.org/bot<TOKEN>/getUpdates`).
3. `cp .env.example .env` and fill both values.
4. Edit `config.yaml` to set the item URL + sku.

## Run (Docker)
    docker compose up -d --build
    docker compose logs -f

## Run (local)
    pip install -r requirements.txt
    python -m monitor.loop

## Test
    python -m pytest -v
