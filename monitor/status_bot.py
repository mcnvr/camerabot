from __future__ import annotations
import json
import logging
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger("monitor")

_API = "https://api.telegram.org/bot{token}/{method}"


class Tracker:
    """Thread-safe record of the latest check per item (site, state, epoch ts).

    Written by the poll loop, read by the /status listener thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, tuple[str, str, float]] = {}

    def record(self, key: str, site: str, state: str, ts: float | None = None) -> None:
        with self._lock:
            self._data[key] = (site, state, ts if ts is not None else time.time())

    def snapshot(self) -> dict[str, tuple[str, str, float]]:
        with self._lock:
            return dict(self._data)


def _state_label(state: str) -> str:
    if state == "IN_STOCK":
        return "✅ IN STOCK"
    if state == "OUT_OF_STOCK":
        return "❌ OUT OF STOCK"
    if state.startswith("ERROR:"):
        return "⚠️ ERROR (retrying)"
    return state


def _ago(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    return f"{s // 3600}h ago"


def format_status(snapshot: dict, now: float, order: list[str] | None = None) -> str:
    """One short message: one line per site with its last result + how long ago."""
    if not snapshot:
        return "📊 Monitor status: no checks recorded yet."
    keys = [k for k in (order or list(snapshot)) if k in snapshot]
    lines = ["📊 Monitor status"]
    for key in keys:
        site, state, ts = snapshot[key]
        lines.append(f"{site}: {_state_label(state)} — {_ago(now - ts)}")
    return "\n".join(lines)


def _api(token: str, method: str, params: dict, timeout: float = 30) -> dict:
    url = _API.format(token=token, method=method)
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(url, data=data, timeout=timeout) as r:
        return json.loads(r.read().decode())


def run_listener(
    token: str,
    authorized_chat_ids: list[str],
    tracker: Tracker,
    order: list[str],
    stop_event: threading.Event,
    poll_timeout: int = 25,
) -> None:
    """Long-poll Telegram getUpdates; reply to /status from authorized chats.

    Only chats in authorized_chat_ids get answered (others are ignored), so a
    stranger who finds the bot can't probe it. Runs until stop_event is set;
    meant to run as a daemon thread alongside the poll loop."""
    allowed = {str(c) for c in authorized_chat_ids}
    offset: int | None = None
    log.info("status listener started (%d authorized chat(s))", len(allowed))
    while not stop_event.is_set():
        try:
            params: dict = {"timeout": poll_timeout}
            if offset is not None:
                params["offset"] = offset
            resp = _api(token, "getUpdates", params, timeout=poll_timeout + 10)
            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = (msg.get("text") or "").strip().lower()
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if not text.startswith("/status"):
                    continue
                if allowed and chat_id not in allowed:
                    log.info("ignoring /status from unauthorized chat %s", chat_id)
                    continue
                body = format_status(tracker.snapshot(), time.time(), order)
                _api(token, "sendMessage", {"chat_id": chat_id, "text": body})
                log.info("answered /status for chat %s", chat_id)
        except Exception as e:  # network blips, 409 webhook conflict, etc.
            log.warning("status listener error: %r", e)
            stop_event.wait(5)
