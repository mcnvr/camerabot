from __future__ import annotations
from monitor.config import Item
from monitor.detector import DetectResult


def format_message(item: Item, state: str, detail: DetectResult | None) -> tuple[str, str]:
    if state == "IN_STOCK":
        price = detail.price if detail and detail.price else "?"
        return (
            f"🟢 IN STOCK: {item.name}",
            f"{item.name} is IN STOCK at ${price}\n{item.url}",
        )
    if state == "OUT_OF_STOCK":
        return (
            f"🔴 OUT OF STOCK: {item.name}",
            f"{item.name} went out of stock.\n{item.url}",
        )
    if state.startswith("ERROR:"):
        signature = state.split(":", 1)[1]
        return (
            f"⚠️ ERROR: {item.name}",
            f"Monitor error for {item.name}: {signature}\n{item.url}",
        )
    # startup/baseline or unknown
    return (
        f"✅ monitor: {item.name}",
        f"{item.name} — current state: {state}\n{item.url}",
    )
