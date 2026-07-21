import threading
import time
import monitor.status_bot as sb
from monitor.status_bot import Tracker, format_status, run_listener


def test_tracker_record_and_snapshot():
    t = Tracker()
    t.record("k1", "CANON", "OUT_OF_STOCK", ts=100.0)
    t.record("k1", "CANON", "IN_STOCK", ts=200.0)   # latest wins
    assert t.snapshot()["k1"] == ("CANON", "IN_STOCK", 200.0)


def test_format_status_empty():
    assert "no checks" in format_status({}, now=0).lower()


def test_format_status_lines_states_and_ages():
    now = 1000.0
    snap = {
        "a": ("CANON", "OUT_OF_STOCK", now - 10),
        "b": ("TARGET", "IN_STOCK", now - 125),
        "c": ("BEST BUY", "ERROR:BROWSER_ERR", now - 3700),
    }
    out = format_status(snap, now, order=["a", "b", "c"])
    assert out.splitlines()[0].startswith("📊")
    assert "CANON: ❌ OUT OF STOCK — 10s ago" in out
    assert "TARGET: ✅ IN STOCK — 2m ago" in out
    assert "BEST BUY: ⚠️ ERROR (retrying) — 1h ago" in out


def test_run_listener_answers_authorized_ignores_others(monkeypatch):
    tracker = Tracker()
    tracker.record("a", "CANON", "OUT_OF_STOCK", ts=time.time())
    stop = threading.Event()
    sent = []
    calls = {"n": 0}

    def fake_api(token, method, params, timeout=30):
        if method == "getUpdates":
            calls["n"] += 1
            if calls["n"] == 1:
                return {"result": [
                    {"update_id": 1, "message": {"text": "/status", "chat": {"id": 111}}},   # authorized
                    {"update_id": 2, "message": {"text": "/status", "chat": {"id": 999}}},   # NOT authorized
                    {"update_id": 3, "message": {"text": "hi", "chat": {"id": 111}}},        # not a command
                ]}
            stop.set()
            return {"result": []}
        if method == "sendMessage":
            sent.append(params)
            return {"ok": True}
        return {"result": []}

    monkeypatch.setattr(sb, "_api", fake_api)
    run_listener("TOKEN", ["111"], tracker, ["a"], stop, poll_timeout=0)

    assert len(sent) == 1                       # exactly one reply
    assert sent[0]["chat_id"] == "111"          # only the authorized chat
    assert "Monitor status" in sent[0]["text"]
