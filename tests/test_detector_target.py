from pathlib import Path
import pytest
from monitor.detector import detect_target, Status, ParseError

FIX = Path(__file__).parent / "fixtures"
TCIN = "91467769"


def _fx(name):
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


def test_out_fixture_has_no_shipping_cell():
    # target_out.html is the real G7X page, out of stock.
    res = detect_target(_fx("target_out.html"), TCIN)
    assert res.status is Status.OUT_OF_STOCK
    assert res.availability_raw == "no-shipping-cell"


def test_in_fixture_has_shipping_cell():
    # target_in.html is a stand-in in-stock PDP (different tcin) — keyed on
    # structure (shipping cell), not the tcin, so any in-stock PDP reads IN.
    html = _fx("target_in.html")
    # detect_target guards on the requested tcin being present; use the tcin the
    # stand-in fixture actually renders so we exercise the shipping-cell branch.
    tcin = "95076868"
    assert tcin in html
    res = detect_target(html, tcin)
    assert res.status is Status.IN_STOCK
    assert res.availability_raw == "ship-to-home"


def test_challenge_page_raises_challenge():
    with pytest.raises(ParseError) as ei:
        detect_target("<html>blocked</html>", TCIN)
    assert ei.value.signature == "CHALLENGE"


def test_unhydrated_skeleton_is_challenge_not_in_stock():
    # Pre-hydration / bot-blocked HTML: __NEXT_DATA__ + tcin present, but the
    # shipping cell is the DISABLED skeleton. Must NOT read as in stock.
    html = f'<html><script id="__NEXT_DATA__">{{"tcin":"{TCIN}"}}</script>' \
           f'<div data-test="fulfillment-cell-shipping" disabled="">Shipping</div></html>'
    with pytest.raises(ParseError) as ei:
        detect_target(html, TCIN)
    assert ei.value.signature == "CHALLENGE"


def test_tcin_present_but_not_a_pdp_raises_challenge():
    with pytest.raises(ParseError) as ei:
        detect_target(f"<html>{TCIN} no next data</html>", TCIN)
    assert ei.value.signature == "CHALLENGE"
