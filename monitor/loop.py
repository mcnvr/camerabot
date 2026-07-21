from __future__ import annotations
import logging
import os
import random
import time

from dotenv import load_dotenv

from monitor.browser_fetch import fetch_browser
from monitor.config import Config, Item, load_config
from monitor.detector import DetectResult, ParseError, detector_for
from monitor.fetcher import FetchError, fetch
from monitor.messages import format_message
from monitor.notify import Notifier
from monitor.state import StateStore

log = logging.getLogger("monitor")

ERROR_CONFIRM_POLLS = 2


def _browser_tier_disabled() -> bool:
    """Runtime kill-switch for the heavy zendriver tier — set on small (1 GB)
    boxes so browser-backed items (Target) are skipped instead of OOM-killing
    the whole container."""
    return os.getenv("DISABLE_BROWSER_TIER", "").strip().lower() in ("1", "true", "yes")


def fetch_for(item: Item):
    """Pick the fetch function for an item: heavy browser tier vs fast curl."""
    return fetch_browser if item.fetcher == "browser" else fetch


def run_cycle(item: Item, fetch_fn, detect_fn) -> tuple[str, DetectResult | None]:
    try:
        try:
            html = fetch_fn(item.url)
        except FetchError as e:
            return f"ERROR:{e.signature}", None
        try:
            res = detect_fn(html, item.sku)
        except ParseError as e:
            return f"ERROR:{e.signature}", None
        return res.status.value, res
    except Exception:
        log.exception("unexpected error in run_cycle for %s", item.name)
        return "ERROR:UNKNOWN", None


def item_interval(item: Item, cfg: Config) -> int:
    """Poll cadence for an item: its own interval_sec, else the global default.

    Lets cheap curl sites (Canon, Best Buy) poll fast while the heavy browser
    site (Target) polls slowly — fewer Chrome launches and a less bot-like
    request cadence against PerimeterX."""
    return item.interval_sec if item.interval_sec is not None else cfg.interval_sec


def _next_due(item: Item, cfg: Config, now: float) -> float:
    return now + item_interval(item, cfg) + random.uniform(0, cfg.jitter_sec)


def confirm_state(pending: dict, key: str, raw_state: str, threshold: int = ERROR_CONFIRM_POLLS) -> str | None:
    """Debounce ERROR: states so a transient blip never gets confirmed.

    Stock states (anything not starting with "ERROR:") are always immediate:
    they clear any pending error count for the key and pass through as-is.

    ERROR: states must be observed `threshold` times in a row (same
    signature) before being confirmed (returned); otherwise None is
    returned to signal "swallow, not yet confirmed". A differing error
    signature resets the count to 1.
    """
    if not raw_state.startswith("ERROR:"):
        pending.pop(key, None)
        return raw_state

    sig, count = pending.get(key, (None, 0))
    if raw_state == sig:
        count += 1
    else:
        count = 1
    pending[key] = (raw_state, count)
    if count < threshold:
        return None
    return raw_state


def process_item(
    item: Item,
    store: StateStore,
    notifier: Notifier,
    fetch_fn,
    detect_fn,
    pending: dict,
    confirm_threshold: int = ERROR_CONFIRM_POLLS,
) -> str:
    """Run one fetch->detect cycle for item and notify on confirmed transitions.

    ERROR: states are debounced via confirm_state before being compared
    against the stored state, so a transient blip (e.g. one Akamai
    challenge poll) never triggers an alert. Stock states (IN/OUT) are
    never delayed.

    Persistence is gated on send success: if notifier.send() fails, the
    stored state is left untouched so the same transition is retried (and
    re-alerted) on the next cycle instead of being silently swallowed.
    """
    raw_state, detail = run_cycle(item, fetch_fn, detect_fn)
    eff = confirm_state(pending, item.key, raw_state, confirm_threshold)
    if eff is None:
        log.info("suppressed transient %s -> %s", item.name, raw_state)
        return raw_state
    prev = store.get(item.key)
    if eff != prev:
        title, body = format_message(item, eff, detail)
        ok = notifier.send(title, body)
        if ok:
            store.set(item.key, eff)
            log.info("NOTIFY %s -> %s", item.name, eff)
        else:
            log.warning("notify failed, will retry %s -> %s", item.name, eff)
    else:
        log.info("no change %s -> %s", item.name, eff)
    return raw_state


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    cfg = load_config("config.yaml")
    store = StateStore("state/state.json")
    notifier = Notifier(cfg.notify_targets)

    # Drop browser-tier items when the kill-switch is set (e.g. 1 GB box).
    items = list(cfg.items)
    if _browser_tier_disabled():
        skipped = [i for i in items if i.fetcher == "browser"]
        for i in skipped:
            log.warning("DISABLE_BROWSER_TIER set — skipping %s [%s]", i.name, i.site)
        items = [i for i in items if i.fetcher != "browser"]

    # Resolve each item's detector + fetch fn once (fails fast on unknown site).
    detectors = {item.key: detector_for(item.site) for item in items}
    fetchers = {item.key: fetch_for(item) for item in items}

    # Startup baseline ping — one per item, then silent until a transition.
    for item in items:
        state, detail = run_cycle(item, fetchers[item.key], detectors[item.key])
        store.set(item.key, state)
        _, body = format_message(item, state, detail)
        notifier.send(f"✅ monitor started — {item.site}", body)
        log.info("startup %s [%s] -> %s", item.name, item.site, state)

    # Per-item scheduling: each item is polled on its own cadence (Target slow,
    # curl sites fast). A 1 s tick checks which items are due.
    pending: dict = {}
    now = time.monotonic()
    next_due = {item.key: _next_due(item, cfg, now) for item in items}
    while True:
        now = time.monotonic()
        for item in items:
            if now >= next_due[item.key]:
                process_item(item, store, notifier, fetchers[item.key], detectors[item.key], pending)
                next_due[item.key] = _next_due(item, cfg, time.monotonic())
        time.sleep(1)


if __name__ == "__main__":
    main()
