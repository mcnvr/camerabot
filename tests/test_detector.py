# tests/test_detector.py
from pathlib import Path
import pytest
from monitor.detector import detect, Status, ParseError

FIX = Path(__file__).parent / "fixtures"

def test_out_of_stock_target_sku():
    html = (FIX / "canon_out.html").read_text(encoding="utf-8", errors="replace")
    res = detect(html, "3637C001")
    assert res.status is Status.OUT_OF_STOCK
    assert res.availability_raw.endswith("/OutOfStock")
    assert res.price == "879.99"

def test_in_stock_fixture():
    # canon_in.html is a PowerShot V1 page (sku 6390C001), verified InStock
    html = (FIX / "canon_in.html").read_text(encoding="utf-8", errors="replace")
    res = detect(html, "6390C001")
    assert res.status is Status.IN_STOCK
    assert res.availability_raw.endswith("/InStock")

def test_unknown_sku_raises():
    html = (FIX / "canon_out.html").read_text(encoding="utf-8", errors="replace")
    with pytest.raises(ParseError):
        detect(html, "0000000")

def test_no_jsonld_raises():
    with pytest.raises(ParseError):
        detect("<html><body>no structured data</body></html>", "3637C001")
