from __future__ import annotations
from monitor.config import Item
from monitor.detector import DetectResult


def format_message(item: Item, state: str, detail: DetectResult | None = None) -> tuple[str, str]:
    """Build (title, body) for a state transition.

    Format is uniform across sites; only the leading status line differs:
        ✅ IN STOCK: {SITE} - {name}
        ❌ OUT OF STOCK: {SITE} - {name}
        ⚠️ ERROR (retrying): {SITE} - {name}
    The link always follows on its own line; ERROR adds a recovery hint.
    """
    site = item.site
    if state == "IN_STOCK":
        line = f"✅ IN STOCK: {site} - {item.name}"
    elif state == "OUT_OF_STOCK":
        line = f"❌ OUT OF STOCK: {site} - {item.name}"
    elif state.startswith("ERROR:"):
        line = f"⚠️ ERROR (retrying): {site} - {item.name}"
        return line, f"{line}\nA non-error status means it's back up.\n{item.url}"
    else:
        # startup baseline or unknown state
        line = f"ℹ️ {state}: {site} - {item.name}"
    return line, f"{line}\n{item.url}"
