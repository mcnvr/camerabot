from monitor.config import Item
from monitor.detector import DetectResult, Status, ParseError
from monitor.fetcher import FetchError
from monitor.loop import run_cycle

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
