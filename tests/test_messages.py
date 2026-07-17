from monitor.config import Item
from monitor.detector import DetectResult, Status
from monitor.messages import format_message

ITEM = Item(name="Canon G7 X III", url="http://x/p", sku="3637C001")

def test_in_stock_message_has_url_and_price():
    detail = DetectResult(Status.IN_STOCK, "https://schema.org/InStock", "879.99", "Canon G7 X III")
    title, body = format_message(ITEM, "IN_STOCK", detail)
    assert "IN STOCK" in title.upper()
    assert "http://x/p" in body
    assert "879.99" in body

def test_out_of_stock_message():
    detail = DetectResult(Status.OUT_OF_STOCK, "https://schema.org/OutOfStock", "879.99", "Canon G7 X III")
    title, body = format_message(ITEM, "OUT_OF_STOCK", detail)
    assert "OUT OF STOCK" in title.upper()

def test_error_message_shows_signature():
    title, body = format_message(ITEM, "ERROR:HTTP_403", None)
    assert "ERROR" in title.upper()
    assert "HTTP_403" in body
