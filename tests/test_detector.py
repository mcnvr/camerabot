# tests/test_detector.py
from pathlib import Path
import pytest
from monitor.detector import (
    detect,
    detect_canon,
    detect_bestbuy,
    detect_target,
    detector_for,
    Status,
    ParseError,
)

FIX = Path(__file__).parent / "fixtures"


def test_detector_for_maps_site_labels():
    assert detector_for("CANON") is detect_canon
    assert detector_for("BEST BUY") is detect_bestbuy   # space-insensitive
    assert detector_for("target") is detect_target       # case-insensitive


def test_detector_for_unknown_site_raises():
    with pytest.raises(ValueError):
        detector_for("newegg")


def test_detect_alias_is_canon():
    assert detect is detect_canon

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
