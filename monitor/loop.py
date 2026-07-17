from __future__ import annotations
import logging
import random
import time

from dotenv import load_dotenv

from monitor.config import Config, Item, load_config
from monitor.detector import DetectResult, ParseError, detect
from monitor.fetcher import FetchError, fetch
from monitor.messages import format_message
from monitor.notify import Notifier
from monitor.state import StateStore

log = logging.getLogger("monitor")


def run_cycle(item: Item, fetch_fn, detect_fn) -> tuple[str, DetectResult | None]:
    try:
        try:
            html = fetch_fn(item.url)
        except FetchError as e:
            return f"ERROR:{e.signature}", None
        try:
            res = detect_fn(html, item.sku)
        except ParseError:
            return "ERROR:PARSE_FAIL", None
        return res.status.value, res
    except Exception:
        log.exception("unexpected error in run_cycle for %s", item.name)
        return "ERROR:UNKNOWN", None


def _sleep_with_jitter(cfg: Config) -> None:
    time.sleep(cfg.interval_sec + random.uniform(0, cfg.jitter_sec))


def process_item(item: Item, store: StateStore, notifier: Notifier, fetch_fn, detect_fn) -> str:
    """Run one fetch->detect cycle for item and notify on transitions.

    Persistence is gated on send success: if notifier.send() fails, the
    stored state is left untouched so the same transition is retried (and
    re-alerted) on the next cycle instead of being silently swallowed.
    """
    state, detail = run_cycle(item, fetch_fn, detect_fn)
    prev = store.get(item.key)
    if state != prev:
        title, body = format_message(item, state, detail)
        ok = notifier.send(title, body)
        if ok:
            store.set(item.key, state)
            log.info("NOTIFY %s -> %s", item.name, state)
        else:
            log.warning("send failed for %s -> %s; will retry next cycle", item.name, state)
    else:
        log.info("no change %s -> %s", item.name, state)
    return state


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    cfg = load_config("config.yaml")
    store = StateStore("state/state.json")
    notifier = Notifier(cfg.notify_targets)

    # Startup baseline ping — one per item, then silent until a transition.
    for item in cfg.items:
        state, detail = run_cycle(item, fetch, detect)
        store.set(item.key, state)
        _, body = format_message(item, state, detail)
        notifier.send(f"✅ monitor started — {item.name}", f"current: {state}\n{body}")
        log.info("startup %s -> %s", item.name, state)

    while True:
        for item in cfg.items:
            process_item(item, store, notifier, fetch, detect)
        _sleep_with_jitter(cfg)


if __name__ == "__main__":
    main()
