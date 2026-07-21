from pathlib import Path
import pytest
from monitor.detector import detect_bestbuy, Status, ParseError

FIX = Path(__file__).parent / "fixtures"
SKU = "6359935"


def _fx(name):
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


def test_out_fixture_is_sold_out():
    res = detect_bestbuy(_fx("bestbuy_out.html"), SKU)
    assert res.status is Status.OUT_OF_STOCK
    assert res.availability_raw == "pdp-sold-out"


def test_in_fixture_is_buyable():
    res = detect_bestbuy(_fx("bestbuy_in.html"), SKU)
    assert res.status is Status.IN_STOCK


def test_challenge_page_raises_challenge():
    # No pdp structure / sku absent => bot wall, not a real out-of-stock read.
    with pytest.raises(ParseError) as ei:
        detect_bestbuy("<html>Access Denied</html>", SKU)
    assert ei.value.signature == "CHALLENGE"


def test_sku_present_but_no_pdp_structure_raises_challenge():
    with pytest.raises(ParseError) as ei:
        detect_bestbuy(f"<html>{SKU} but no product markup</html>", SKU)
    assert ei.value.signature == "CHALLENGE"
