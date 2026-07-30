"""Tooling layer for Day 112 reflection node."""

from __future__ import annotations

from typing import Any

_INVENTORY: dict[str, tuple[str, float, int]] = {
    "SKU-1001": ("边缘推理加速卡", 1299.0, 12),
    "SKU-2002": ("向量检索一体机", 4599.0, 3),
    "SKU-3003": ("标注工作站", 899.0, 25),
}


def lookup_stock(sku: str) -> str:
    key = sku.strip().upper()
    item = _INVENTORY.get(key)
    if item is None:
        return f"未找到 SKU={key}。可选：{', '.join(_INVENTORY)}"
    name, price, qty = item
    return f"sku={key}; name={name}; unit_price_usd={price}; stock_qty={qty}"


def calc_quote(unit_price_usd: float, quantity: int) -> str:
    if quantity <= 0:
        return "quantity 必须为正整数"
    subtotal = round(unit_price_usd * quantity, 2)
    return f"quantity={quantity}; unit_price_usd={unit_price_usd}; subtotal_usd={subtotal}"


def fetch_citation_count(doc_id: str, *, force_fail: bool = False) -> int:
    """Synthetic external tool used to verify failure fallback path."""
    if force_fail or doc_id.endswith("FAIL"):
        raise RuntimeError(f"citation service unavailable for {doc_id}")
    return max(1, (sum(ord(c) for c in doc_id) % 20))


def tool_summary(doc_id: str, *, force_fail: bool = False) -> dict[str, Any]:
    count = fetch_citation_count(doc_id, force_fail=force_fail)
    stock = lookup_stock("SKU-1001")
    quote = calc_quote(1299.0, 2)
    return {
        "citation_count": count,
        "stock": stock,
        "quote": quote,
    }
