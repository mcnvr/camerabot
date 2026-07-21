# monitor/detector.py
from __future__ import annotations
import enum
import json
import re
from dataclasses import dataclass

_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)


class Status(enum.Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


@dataclass
class DetectResult:
    status: Status
    availability_raw: str
    price: str | None
    name: str | None


class ParseError(Exception):
    """Detection failed. `signature` is the coarse error label surfaced to the
    error state machine (e.g. PARSE_FAIL, CHALLENGE) so a bot-wall page reads as
    a transient challenge rather than a code-level parse bug."""

    def __init__(self, message: str, signature: str = "PARSE_FAIL"):
        super().__init__(message)
        self.signature = signature


def _iter_offers(node):
    """Yield (product_node, offer_node) pairs found anywhere in the JSON-LD tree."""
    if isinstance(node, dict):
        if "offers" in node:
            offers = node["offers"]
            for off in (offers if isinstance(offers, list) else [offers]):
                if isinstance(off, dict) and "availability" in off:
                    yield node, off
        for v in node.values():
            yield from _iter_offers(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_offers(v)


def detect_canon(html: str, sku: str) -> DetectResult:
    """Canon: JSON-LD ProductGroup, offers.availability ends with /InStock.

    No JSON-LD at all means Canon served an Akamai challenge interstitial, not
    the product page, so that reads as CHALLENGE (transient) not PARSE_FAIL.
    """
    blocks = _LD_RE.findall(html)
    if not blocks:
        raise ParseError("no application/ld+json block found", signature="CHALLENGE")

    for block in blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for product, offer in _iter_offers(data):
            if str(product.get("sku")) != sku:
                continue
            avail = offer.get("availability")
            if not isinstance(avail, str):
                raise ParseError(f"sku {sku} offer missing availability")
            status = Status.IN_STOCK if avail.rstrip("/").endswith("InStock") else Status.OUT_OF_STOCK
            price = offer.get("price")
            return DetectResult(
                status=status,
                availability_raw=avail,
                price=str(price) if price is not None else None,
                name=product.get("name"),
            )

    raise ParseError(f"sku {sku} not found in JSON-LD offers")


# Back-compat alias: `detect` is the Canon detector.
detect = detect_canon


def detect_bestbuy(html: str, sku: str) -> DetectResult:
    """Best Buy: server-rendered SKU-keyed sold-out label.

    Best Buy's JSON-LD carries no availability, but the PDP renders
    `data-testid="pdp-sold-out-{sku}"` when the SKU is sold out — present =
    OUT, absent = IN. The `pdp-` structural marker guards against an Akamai
    challenge page (which lacks it) being misread as in stock.
    """
    if sku not in html or "pdp-" not in html:
        raise ParseError(f"best buy pdp for {sku} not present", signature="CHALLENGE")
    sold_out = f'pdp-sold-out-{sku}' in html
    return DetectResult(
        status=Status.OUT_OF_STOCK if sold_out else Status.IN_STOCK,
        availability_raw="pdp-sold-out" if sold_out else "buyable",
        price=None,
        name=None,
    )


def detect_target(html: str, sku: str) -> DetectResult:
    """Target: SSR shipping fulfillment cell.

    Target is a Next.js SPA but server-renders the fulfillment section into the
    raw HTML. `data-test="fulfillment-cell-shipping"` present = ship-to-home
    available (IN); absent = OUT. Same-day-delivery / in-store-pickup cells are
    intentionally NOT treated as in stock. `__NEXT_DATA__` + the tcin guard
    against a challenge/blocked page reading as OUT.
    """
    if sku not in html or "__NEXT_DATA__" not in html:
        raise ParseError(f"target pdp for {sku} not present", signature="CHALLENGE")
    # The shipping cell renders as a DISABLED skeleton before client-side
    # hydration and is ALWAYS present in the raw/pre-hydration HTML. A blocked or
    # incomplete render (e.g. PerimeterX challenging a datacenter IP, so the
    # redsky fulfillment XHR never lands) leaves exactly that skeleton — reading
    # it as "in stock" is a false positive. Only an ENABLED cell means buyable;
    # the skeleton means "couldn't determine", which is a CHALLENGE, not a sale.
    if 'data-test="fulfillment-cell-shipping" disabled' in html:
        raise ParseError("target not hydrated (skeleton shipping cell)", signature="CHALLENGE")
    in_stock = 'data-test="fulfillment-cell-shipping"' in html
    return DetectResult(
        status=Status.IN_STOCK if in_stock else Status.OUT_OF_STOCK,
        availability_raw="ship-to-home" if in_stock else "no-shipping-cell",
        price=None,
        name=None,
    )


DETECTORS = {
    "CANON": detect_canon,
    "BESTBUY": detect_bestbuy,
    "TARGET": detect_target,
}


def detector_for(site: str):
    """Map a config `site` label (e.g. "BEST BUY") to its detector function."""
    key = "".join(ch for ch in site.upper() if ch.isalpha())
    try:
        return DETECTORS[key]
    except KeyError:
        raise ValueError(f"unknown site {site!r} (known: {sorted(DETECTORS)})")
