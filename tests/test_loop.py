from monitor.config import Item
from monitor.detector import DetectResult, Status, ParseError
from monitor.fetcher import FetchError
from monitor.loop import run_cycle, process_item
from monitor.state import StateStore

ITEM = Item(name="X", url="http://x", sku="3637C001")

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

    state = process_item(ITEM, store, notifier, fetch_fn, detect_fn)
    assert state == "OUT_OF_STOCK"
    assert store.get(ITEM.key) is None  # failed send must not persist the transition

    state = process_item(ITEM, store, notifier, fetch_fn, detect_fn)
    assert state == "OUT_OF_STOCK"
    assert store.get(ITEM.key) == "OUT_OF_STOCK"  # retried and persisted on success
    assert notifier.calls == 2


def test_process_item_persists_and_notifies_on_successful_transition(tmp_path):
    store = StateStore(tmp_path / "state.json")
    fetch_fn = lambda url: "<html/>"
    detect_fn = lambda html, sku: DetectResult(Status.IN_STOCK, "https://schema.org/InStock", "9.99", "X")
    notifier = _RecordingNotifier(result=True)

    state = process_item(ITEM, store, notifier, fetch_fn, detect_fn)
    assert state == "IN_STOCK"
    assert store.get(ITEM.key) == "IN_STOCK"
    assert len(notifier.sent) == 1


def test_process_item_no_change_skips_notify(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.set(ITEM.key, "OUT_OF_STOCK")
    fetch_fn = lambda url: "<html/>"
    detect_fn = lambda html, sku: DetectResult(Status.OUT_OF_STOCK, "https://schema.org/OutOfStock", "9.99", "X")
    notifier = _RecordingNotifier(result=True)

    state = process_item(ITEM, store, notifier, fetch_fn, detect_fn)
    assert state == "OUT_OF_STOCK"
    assert notifier.sent == []
