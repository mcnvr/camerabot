from monitor.config import Item
from monitor.detector import DetectResult, Status, ParseError
from monitor.fetcher import FetchError, fetch as curl_fetch
from monitor.browser_fetch import fetch_browser
from monitor.loop import (
    run_cycle,
    process_item,
    confirm_state,
    fetch_for,
    _browser_tier_disabled,
    ERROR_CONFIRM_POLLS,
)
from monitor.state import StateStore

ITEM = Item(name="X", url="http://x", sku="3637C001")


def test_fetch_for_selects_tier_by_item():
    assert fetch_for(Item(name="c", url="u", sku="1", fetcher="curl_cffi")) is curl_fetch
    assert fetch_for(Item(name="b", url="u", sku="2", fetcher="browser")) is fetch_browser


def test_browser_tier_disabled_reads_env(monkeypatch):
    monkeypatch.delenv("DISABLE_BROWSER_TIER", raising=False)
    assert _browser_tier_disabled() is False
    monkeypatch.setenv("DISABLE_BROWSER_TIER", "1")
    assert _browser_tier_disabled() is True
    monkeypatch.setenv("DISABLE_BROWSER_TIER", "false")
    assert _browser_tier_disabled() is False

def test_cycle_in_stock():
    fetch_fn = lambda url: "<html/>"
    detect_fn = lambda html, sku: DetectResult(Status.IN_STOCK, "https://schema.org/InStock", "879.99", "X")
    state, detail = run_cycle(ITEM, fetch_fn, detect_fn)
    assert state == "IN_STOCK"
    assert detail.price == "879.99"

def test_cycle_out_of_stock():
    fetch_fn = lambda url: "<html/>"
    detect_fn = lambda html, sku: DetectResult(Status.OUT_OF_STOCK, "https://schema.org/OutOfStock", "879.99", "X")
    state, detail = run_cycle(ITEM, fetch_fn, detect_fn)
    assert state == "OUT_OF_STOCK"

def test_cycle_fetch_error_maps_signature():
    def fetch_fn(url):
        raise FetchError("HTTP_403")
    detect_fn = lambda html, sku: None
    state, detail = run_cycle(ITEM, fetch_fn, detect_fn)
    assert state == "ERROR:HTTP_403"
    assert detail is None

def test_cycle_parse_error_maps_to_parse_fail():
    fetch_fn = lambda url: "<html/>"
    def detect_fn(html, sku):
        raise ParseError("no sku")
    state, detail = run_cycle(ITEM, fetch_fn, detect_fn)
    assert state == "ERROR:PARSE_FAIL"

def test_cycle_unexpected_exception_maps_to_unknown():
    def fetch_fn(url):
        raise ValueError("boom")
    detect_fn = lambda html, sku: None
    state, detail = run_cycle(ITEM, fetch_fn, detect_fn)
    assert state == "ERROR:UNKNOWN"
    assert detail is None


class _FlakyNotifier:
    """send() fails the first call, succeeds thereafter."""
    def __init__(self):
        self.calls = 0

    def send(self, title, body):
        self.calls += 1
        return self.calls > 1


class _RecordingNotifier:
    def __init__(self, result=True):
        self.result = result
        self.sent = []

    def send(self, title, body):
        self.sent.append((title, body))
        return self.result


def test_process_item_retries_transition_after_failed_send(tmp_path):
    store = StateStore(tmp_path / "state.json")
    fetch_fn = lambda url: "<html/>"
    detect_fn = lambda html, sku: DetectResult(Status.OUT_OF_STOCK, "https://schema.org/OutOfStock", "9.99", "X")
    notifier = _FlakyNotifier()
    pending = {}

    state = process_item(ITEM, store, notifier, fetch_fn, detect_fn, pending)
    assert state == "OUT_OF_STOCK"
    assert store.get(ITEM.key) is None  # failed send must not persist the transition

    state = process_item(ITEM, store, notifier, fetch_fn, detect_fn, pending)
    assert state == "OUT_OF_STOCK"
    assert store.get(ITEM.key) == "OUT_OF_STOCK"  # retried and persisted on success
    assert notifier.calls == 2


def test_process_item_persists_and_notifies_on_successful_transition(tmp_path):
    store = StateStore(tmp_path / "state.json")
    fetch_fn = lambda url: "<html/>"
    detect_fn = lambda html, sku: DetectResult(Status.IN_STOCK, "https://schema.org/InStock", "9.99", "X")
    notifier = _RecordingNotifier(result=True)
    pending = {}

    state = process_item(ITEM, store, notifier, fetch_fn, detect_fn, pending)
    assert state == "IN_STOCK"
    assert store.get(ITEM.key) == "IN_STOCK"
    assert len(notifier.sent) == 1


def test_process_item_no_change_skips_notify(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.set(ITEM.key, "OUT_OF_STOCK")
    fetch_fn = lambda url: "<html/>"
    detect_fn = lambda html, sku: DetectResult(Status.OUT_OF_STOCK, "https://schema.org/OutOfStock", "9.99", "X")
    notifier = _RecordingNotifier(result=True)
    pending = {}

    state = process_item(ITEM, store, notifier, fetch_fn, detect_fn, pending)
    assert state == "OUT_OF_STOCK"
    assert notifier.sent == []


# --- confirm_state (error-state debounce) ---------------------------------

def test_confirm_state_non_error_returns_raw_and_clears_pending():
    pending = {"X": ("ERROR:CHALLENGE", 1)}
    result = confirm_state(pending, "X", "IN_STOCK")
    assert result == "IN_STOCK"
    assert "X" not in pending


def test_confirm_state_first_error_is_swallowed_then_confirmed_on_repeat():
    pending = {}
    first = confirm_state(pending, "X", "ERROR:CHALLENGE")
    assert first is None
    second = confirm_state(pending, "X", "ERROR:CHALLENGE")
    assert second == "ERROR:CHALLENGE"


def test_confirm_state_different_signature_resets_count():
    pending = {}
    confirm_state(pending, "X", "ERROR:CHALLENGE")  # count=1, swallowed
    result = confirm_state(pending, "X", "ERROR:PARSE_FAIL")  # different sig -> reset to 1
    assert result is None
    assert pending["X"] == ("ERROR:PARSE_FAIL", 1)


def test_confirm_state_stock_after_pending_error_pops_and_returns_stock():
    pending = {}
    confirm_state(pending, "X", "ERROR:CHALLENGE")  # pending now set
    assert "X" in pending
    result = confirm_state(pending, "X", "OUT_OF_STOCK")
    assert result == "OUT_OF_STOCK"
    assert "X" not in pending


# --- process_item + confirm_state integration (real-world blip scenario) --

def test_process_item_transient_error_blip_never_alerts(tmp_path):
    """OUT_OF_STOCK -> (1 poll) ERROR:CHALLENGE -> OUT_OF_STOCK must alert ZERO times."""
    store = StateStore(tmp_path / "state.json")
    store.set(ITEM.key, "OUT_OF_STOCK")  # baseline, as if startup already ran
    notifier = _RecordingNotifier(result=True)
    pending = {}

    out_fetch = lambda url: "<html/>"
    out_detect = lambda html, sku: DetectResult(Status.OUT_OF_STOCK, "https://schema.org/OutOfStock", "9.99", "X")

    def error_fetch(url):
        raise FetchError("CHALLENGE")
    error_detect = lambda html, sku: None

    # 1: still OUT_OF_STOCK (no change)
    state = process_item(ITEM, store, notifier, out_fetch, out_detect, pending)
    assert state == "OUT_OF_STOCK"

    # 2: transient ERROR:CHALLENGE blip — must be swallowed, not alerted
    state = process_item(ITEM, store, notifier, error_fetch, error_detect, pending)
    assert state == "ERROR:CHALLENGE"

    # 3: back to OUT_OF_STOCK — recovery must not alert either, since the
    # error was never confirmed/stored in the first place.
    state = process_item(ITEM, store, notifier, out_fetch, out_detect, pending)
    assert state == "OUT_OF_STOCK"

    assert notifier.sent == []  # ZERO alerts for the whole transient blip
    assert store.get(ITEM.key) == "OUT_OF_STOCK"  # store never moved off baseline


def test_process_item_sustained_error_notifies_once_then_dedups(tmp_path):
    """Two consecutive ERROR:CHALLENGE cycles confirm and notify once; a third dedups."""
    store = StateStore(tmp_path / "state.json")
    store.set(ITEM.key, "OUT_OF_STOCK")  # baseline
    notifier = _RecordingNotifier(result=True)
    pending = {}

    def error_fetch(url):
        raise FetchError("CHALLENGE")
    error_detect = lambda html, sku: None

    # 1st ERROR:CHALLENGE — swallowed, not yet confirmed
    state = process_item(ITEM, store, notifier, error_fetch, error_detect, pending)
    assert state == "ERROR:CHALLENGE"
    assert notifier.sent == []
    assert store.get(ITEM.key) == "OUT_OF_STOCK"

    # 2nd consecutive ERROR:CHALLENGE — confirmed, notifies once
    state = process_item(ITEM, store, notifier, error_fetch, error_detect, pending)
    assert state == "ERROR:CHALLENGE"
    assert len(notifier.sent) == 1
    assert store.get(ITEM.key) == "ERROR:CHALLENGE"

    # 3rd consecutive ERROR:CHALLENGE — already stored, no re-notify (dedup)
    state = process_item(ITEM, store, notifier, error_fetch, error_detect, pending)
    assert state == "ERROR:CHALLENGE"
    assert len(notifier.sent) == 1
