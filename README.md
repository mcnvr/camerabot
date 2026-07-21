# resellbot — Canon G7 X III restock monitor

Polls Canon, Best Buy, and Target for the Canon PowerShot G7 X Mark III (Black)
and sends a Telegram alert on every stock/error state change.

## How each site is checked

| Site | Fetch | Signal | Cost |
|------|-------|--------|------|
| **Canon** | curl_cffi (Chrome TLS impersonation) | JSON-LD `offers.availability` in raw HTML | ~200 ms, ~300 MB |
| **Best Buy** | curl_cffi | server-rendered `data-testid="pdp-sold-out-{sku}"` | ~200 ms |
| **Target** | **headless Chrome (zendriver)** | JS-hydrated `fulfillment-cell-shipping` | ~5–10 s, **~1 GB RAM** |

Target's stock is loaded client-side from an API behind PerimeterX, so plain
HTTP can't read it — it needs a real browser. Canon + Best Buy do not.

## RAM / the browser tier

The Target check launches Chromium per poll (memory released after each check).
It needs **~2 GB RAM**. On a **1 GB** box, set `DISABLE_BROWSER_TIER=1` in `.env`
— Canon + Best Buy keep running; Target is skipped (no Chromium launched).

## Setup
1. Create a Telegram bot via @BotFather → get `TELEGRAM_BOT_TOKEN`.
2. Get your numeric chat id (message the bot, then check `https://api.telegram.org/bot<TOKEN>/getUpdates`).
3. `cp .env.example .env` and fill both values. On a 1 GB box also add `DISABLE_BROWSER_TIER=1`.
4. Edit `config.yaml` — items, poll interval, and per-item `fetcher` (`curl_cffi` or `browser`).

## Run (Docker)
    docker compose up -d --build
    docker compose logs -f

## Run (local)
    pip install -r requirements.txt        # zendriver + a local Chrome/Chromium for the Target tier
    python -m monitor.loop

## Test
    python -m pytest -v
