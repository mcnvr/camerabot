from monitor.config import Item
from monitor.messages import format_message

ITEM = Item(name="Canon PowerShot G7 X Mark III (Black)", url="http://x/p", sku="6359935", site="BEST BUY")


def test_in_stock_message_has_site_name_and_url():
    title, body = format_message(ITEM, "IN_STOCK", None)
    assert title == "✅ IN STOCK: BEST BUY - Canon PowerShot G7 X Mark III (Black)"
    assert "http://x/p" in body


def test_out_of_stock_message_has_site_name_and_url():
    title, body = format_message(ITEM, "OUT_OF_STOCK", None)
    assert title == "❌ OUT OF STOCK: BEST BUY - Canon PowerShot G7 X Mark III (Black)"
    assert "http://x/p" in body


def test_error_message_is_uniform_with_recovery_hint():
    title, body = format_message(ITEM, "ERROR:HTTP_403", None)
    assert title == "⚠️ ERROR (retrying): BEST BUY - Canon PowerShot G7 X Mark III (Black)"
    assert "back up" in body
    assert "http://x/p" in body
    # signature is an ops/log detail, not surfaced to the recipient
    assert "HTTP_403" not in body
