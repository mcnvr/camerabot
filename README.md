# resellbot — Canon G7 X III restock monitor

Polls **Canon**, **Best Buy**, and **Target** for the Canon PowerShot G7 X Mark III
(Black) and sends a **Telegram** alert on every stock/error state change.

Alerts look like:

```
✅ IN STOCK: BEST BUY - Canon PowerShot G7 X Mark III (Black)
https://www.bestbuy.com/...

❌ OUT OF STOCK: TARGET - Canon PowerShot G7 X Mark III (Black)
https://www.target.com/...

⚠️ ERROR (retrying): CANON - Canon PowerShot G7 X Mark III (Black)
A non-error status means it's back up.
https://www.usa.canon.com/...
```

---

## How each site is checked

| Site | Fetch | Signal | Per-check cost |
|------|-------|--------|----------------|
| **Canon** | curl (Chrome TLS impersonation) | JSON-LD `offers.availability` | ~0.2 s, light |
| **Best Buy** | curl | server-rendered `pdp-sold-out-{sku}` | ~0.2 s, light |
| **Target** | **headless Chrome** (zendriver) | JS-hydrated shipping cell | ~5–10 s, **~1 GB RAM** |

Target's stock is loaded client-side from an API behind PerimeterX, so plain HTTP
can't read it — it needs a real browser. Canon + Best Buy don't.

---

## Requirements to run WITH Target

- A host with **≥ 2 GB RAM** (Target launches Chromium). 1 GB → see [1 GB fallback](#1-gb-fallback).
- **Docker** + **docker compose**.
- A **Telegram bot token** and your **chat id** (steps below).

---

## Step 1 — Create the Telegram bot

1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy the **bot token**
   (looks like `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`).
2. Send any message to your new bot (so it can DM you).
3. Get your numeric **chat id**: open
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and read
   `result[].message.chat.id`.

## Step 2 — Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:

```
TELEGRAM_BOT_TOKEN=123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=8753883817
```

(Leave `DISABLE_BROWSER_TIER` unset/commented on a 2 GB box — that keeps Target ON.)

Lock it down: `chmod 600 .env`.

To alert **multiple people**, add more chat ids under `notify.telegram.chat_ids`
in `config.yaml` (one per line).

## Step 3 — (optional) review `config.yaml`

Already set to the 3 Canon G7 X III listings. Poll cadence:

- Canon + Best Buy: `interval_sec: 60` (global default) + up to 15 s jitter.
- Target: `interval_sec: 180` (its own override — deliberately slow; see
  [Polling](#polling--why-target-is-slow)).

## Step 4 — Build & run

```bash
docker compose up -d --build      # first build pulls Chromium (~400 MB, one time)
docker compose logs -f            # watch it
```

On startup it sends **one baseline ping per site** (so you know it's alive), then
stays quiet until a state actually changes.

## Step 5 — Verify

In the logs you should see, within ~3 minutes, one line per site:

```
startup Canon... [CANON] -> OUT_OF_STOCK
startup Canon... [BEST BUY] -> OUT_OF_STOCK
startup Canon... [TARGET] -> OUT_OF_STOCK     # Target line takes ~10s (browser)
```

and three baseline Telegram messages. If the Target line never appears, check
[Troubleshooting](#troubleshooting).

State persists across restarts in a Docker volume (`monitor-state`), so a restart
won't re-alert you for the current state.

---

## 1 GB fallback

Target's browser tier needs ~2 GB. On a **1 GB** box, add to `.env`:

```
DISABLE_BROWSER_TIER=1
```

Canon + Best Buy keep running (fast, light); Target is skipped entirely — Chromium
is never launched, so no OOM risk. Flip it back off once you're on ≥ 2 GB.

---

## Polling — why Target is slow

Each item polls on its own schedule. Curl sites are cheap, so they poll every
~60 s. **Target is deliberately ~180 s** because each check is a full Chrome
launch/render against PerimeterX:

- **Bot-detection risk** — frequent, metronomic automated visits from one IP are
  exactly what PerimeterX blocks. Slower + jittered lasts far longer before it
  starts serving captchas.
- **CPU** — a render is ~5–10 s of work on your single core; 60 s cadence wastes
  it for no benefit.
- **Catch rate** — a restock isn't decided by 60 s vs 180 s; it sits in stock for
  minutes (caught either way) or sells out in seconds (no interval helps).

Change `interval_sec` under the Target item in `config.yaml` if you want.

---

## Add another alert recipient

The same bot can alert multiple people:

1. The new person opens **@CameraStockAlertBot** and taps **Start** (so the bot is
   allowed to DM them).
2. Get their numeric chat id: `https://api.telegram.org/bot<TOKEN>/getUpdates` →
   find their message's `chat.id`.
3. Add it under `notify.telegram.chat_ids` in `config.yaml` (a literal id, or a
   `{ENV_VAR}` reference):

   ```yaml
   notify:
     telegram:
       bot_token: "{TELEGRAM_BOT_TOKEN}"
       chat_ids:
         - "{TELEGRAM_CHAT_ID}"
         - "8753883817"        # second recipient
   ```
4. `docker compose up -d` to reload. New recipients also get answers to `/status`.

## `/status` command

Message **`/status`** to the bot at any time; it replies with one short message —
the latest result per site and how long ago it was checked:

```
📊 Monitor status
CANON: ❌ OUT OF STOCK — 12s ago
BEST BUY: ❌ OUT OF STOCK — 44s ago
TARGET: ❌ OUT OF STOCK — 2m ago
```

Only chat ids listed in `config.yaml` are answered — a stranger who finds the bot
gets ignored.

## Troubleshooting

- **Target check errors (`ERROR ... BROWSER_ERR` / `CHALLENGE`)** — PerimeterX may
  be challenging Chromium. Transient blips are debounced (you won't get spammed);
  sustained errors alert once. If it persists, raise `interval_sec` for Target, or
  restart the container to get a fresh session.
- **Container keeps restarting / OOM** — you're likely on < 2 GB with the browser
  tier on. Set `DISABLE_BROWSER_TIER=1`, or move to a bigger box.
- **No Telegram messages** — bad token/chat id. Re-check Step 1; watch
  `docker compose logs` for `notify failed`.

---

## Run locally (no Docker)

Needs a local Chrome/Chromium for the Target tier.

```bash
pip install -r requirements.txt
python -m monitor.loop
```

## Test

```bash
python -m pytest -v      # 58 tests
```
