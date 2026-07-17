# Canon Restock Monitor — Design

**Date:** 2026-07-17
**Status:** Approved (architecture), pending spec review

## Goal

Monitor a product page for restock and send an instant Telegram alert when it
flips from out-of-stock to in-stock. Runs 24/7 in a Docker container on the
user's VPS. Optimized for speed and low notification spam. Starting target:
Canon PowerShot G7 X Mark III (Black), `https://www.usa.canon.com/shop/p/powershot-g7-x-mark-iii?color=Black&type=New`.

**Now:** alert only. **Later (out of scope, but design must not preclude):** optional
auto-buy when it aligns with site ToS.

## Confirmed findings (from live inspection)

1. **Anti-bot:** Canon runs Akamai Bot Manager. Plain `curl`/`requests` →
   `HTTP 403 Access Denied` (`server: AkamaiGHost`, `errors.edgesuite.net`).
   Must defeat Akamai to read the page.
2. **Stock signal:** One `application/ld+json` block per page, a `ProductGroup`
   with `hasVariant[]`. Each variant is a `Product` with `sku` and nested
   `offers.availability`.
   - Target variant **Black = sku `3637C001`** (Silver = `3638C001`, ignored).
   - Out-of-stock value: `https://schema.org/OutOfStock` (verified on target page).
   - In-stock value: `https://schema.org/InStock` (verified on a live in-stock
     Canon page, PowerShot V1).
3. **Detector rule:** `in_stock = offers.availability endswith "/InStock"` for the
   matched sku. Store the raw availability string in state so any unexpected new
   vocab (e.g. `BackOrder`) is visible in logs rather than silently miscounted.

## Architecture

One small Docker container running a polling loop. Three units behind clean
interfaces so pieces swap without a rebuild:

```
loop.py  ──►  fetcher  ──►  detector  ──►  state  ──►  notify
(interval    (get past     (parse JSON-LD  (edge-      (Telegram
 + jitter)    Akamai)       → status)      trigger)     via Apprise)
                                              │
                                          state.json
```

- **fetcher** — returns raw HTML for a URL, defeating Akamai. Pluggable strategy
  (see below). Raises `FetchError(signature)` on failure (403, timeout, etc.).
- **detector** — parses JSON-LD, finds the variant by `sku`, returns
  `Status.IN_STOCK` / `Status.OUT_OF_STOCK`. Raises `ParseError` if the JSON-LD
  or sku is missing (page shape changed).
- **state** — persists last-notified state per item in `state.json`. Decides
  whether the current cycle is a transition worth notifying (edge-triggered
  state machine, below).
- **notify** — Apprise wrapper. Telegram target from config/env. Sends the
  formatted message.
- **loop** — scheduler. For each item, every `interval_sec` ± jitter: fetch →
  detect → update state → notify on transition. Catches errors and routes them
  through the same state machine as `ERROR:<signature>`.

## Fetcher strategy

**Start with Strategy B (`curl_cffi`)** — chosen because polling is moderate
(30–60s), so ban risk is low and a full browser is unjustified overhead.

- **B (start here):** `curl_cffi` with Chrome TLS/JA3 impersonation
  (`impersonate="chrome"`). Fast (~150–400ms), tiny footprint (no browser).
  Sends a realistic Chrome header set. If Akamai serves the page to a real
  Chrome without a JS challenge, this passes.
- **Escalation to C (hybrid) — only if B gets 403 in the implementation spike:**
  Playwright headless Chrome runs once to mint Akamai cookies (`_abck`, `bm_sz`,
  `ak_bmsc`), which are then replayed on fast `curl_cffi` calls. Re-mint when
  cookies expire or a 403 returns. Same detector/notify — only `fetcher.py`
  changes. Design keeps the fetcher interface identical so escalation is
  additive.

**Implementation spike (first task):** run `curl_cffi` once against the target
URL. If 200 → build detector on the real body. If 403 → implement Strategy C
before proceeding.

## State machine (edge-triggered, de-spammed)

Each item has one **current state**, one of:

- `IN_STOCK`
- `OUT_OF_STOCK`
- `ERROR:<signature>` — normalized signature, e.g. `ERROR:HTTP_403`,
  `ERROR:TIMEOUT`, `ERROR:PARSE_FAIL`. Bucketed by type, not exact text, so a
  403 storm whose reference number changes each time is still one signature.

Notify **only when the effective state differs from the last-notified state:**

| Transition | Notify |
|---|---|
| OUT_OF_STOCK → IN_STOCK | ✅ restock alert |
| IN_STOCK → OUT_OF_STOCK | ✅ went out of stock |
| any → ERROR (new signature) | ✅ error alert (once) |
| ERROR → ERROR (same signature) | ❌ silent |
| ERROR → ERROR (different signature) | ✅ new error alert |
| ERROR → IN_STOCK / OUT_OF_STOCK | ✅ normal stock alert (implies recovery) |

**Startup ping:** on boot, send one `✅ monitor started, current: <state>` per
item so the user knows it is alive; then silent until a transition.

State persists to `state.json` (last-notified state + raw availability +
timestamp per item), surviving container restarts so a restart does not
re-alert an unchanged state.

## Config

`config.yaml` (checked in, no secrets):

```yaml
interval_sec: 45          # base poll interval per item
jitter_sec: 15            # random 0..jitter added each cycle
fetcher: curl_cffi        # curl_cffi | hybrid (escalation)
items:
  - name: "Canon G7 X Mark III (Black)"
    url: "https://www.usa.canon.com/shop/p/powershot-g7-x-mark-iii?color=Black&type=New"
    sku: "3637C001"
notify:
  # Apprise URL built from env; see .env
  targets:
    - "tgram://{TELEGRAM_BOT_TOKEN}/{TELEGRAM_CHAT_ID}"
```

`.env` (gitignored) holds secrets:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Add a new item/site = add a `config.yaml` entry (+ a detector adapter only if a
different site uses a different stock signal). No code change for another Canon
item.

## Notifications

[Apprise](https://github.com/caronc/apprise) (Apache-2.0, Python) as the notify
layer — one library, channel is pure config. Telegram now
(`tgram://token/chat_id`); swap/add Discord, ntfy, etc. later without code
changes. Message includes item name, status, price, and the product URL.

## Deployment

- **Dockerfile:** slim Python base, `pip install -r requirements.txt`, copy
  `monitor/`, run `python -m monitor.loop`.
- **docker-compose.yml:** one service, `restart: unless-stopped`, `.env`
  mounted, `state.json` on a named volume so state survives redeploys.
- Runs on the user's existing VPS. `curl_cffi` path needs no browser, so the
  image stays small. (If escalated to hybrid C, the image adds Playwright +
  Chromium — larger, still fine on a VPS.)

## Dependencies (`requirements.txt`)

- `curl_cffi` — TLS-impersonation HTTP client (Strategy B)
- `apprise` — notifications (Telegram)
- `pyyaml` — config
- `selectolax` — fast HTML parse (fallback if a signal ever needs DOM, not just
  JSON-LD); JSON-LD itself parses with stdlib `json` + `re`
- (escalation only) `playwright` — Strategy C cookie harvest

## Testing

- **detector unit tests** against the two saved fixtures (`canon.html` =
  out-of-stock → `OUT_OF_STOCK`; `canon_instock.html` = in-stock →
  `IN_STOCK`). Deterministic, no network.
- **state machine unit tests** — drive a sequence of statuses/errors, assert
  exactly which transitions notify (table above), with a fake notify sink.
- **fetcher** — smoke test hitting the live URL, asserting 200 + non-empty body
  (marked network/integration, not run in CI by default).

## File layout

```
resellbot/
├─ monitor/
│  ├─ __init__.py
│  ├─ loop.py
│  ├─ fetcher.py
│  ├─ detector.py
│  ├─ state.py
│  └─ notify.py
├─ tests/
│  ├─ test_detector.py
│  ├─ test_state.py
│  └─ fixtures/            # canon.html, canon_instock.html copied here
├─ config.yaml
├─ requirements.txt
├─ Dockerfile
├─ docker-compose.yml
├─ .env.example
├─ .gitignore             # .env, state.json, *.html
└─ docs/superpowers/specs/2026-07-17-canon-restock-monitor-design.md
```

## Risks & open items

- **Akamai may block Strategy B.** Mitigated by the spike-first plan and the
  pre-designed escalation to C.
- **Page shape change** (Canon drops/moves JSON-LD): detector raises
  `ParseError` → surfaces as `ERROR:PARSE_FAIL` alert rather than silent
  false-negative.
- **Aggressive polling ban:** avoided by 30–60s + jitter; not sub-15s.
- **Auto-buy (future):** intentionally out of scope. The transition hook in
  `state` is the natural extension point; revisit ToS before building.

## Out of scope (YAGNI for v1)

- Auto-buy / checkout automation.
- Multi-site adapters beyond Canon (design supports adding them; not built).
- Web UI / dashboard. Logs + Telegram only.
- Distributed / multi-worker scaling.
