"""Amaran product catalog matching and capability classification."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from .const import COLOR_MODE_BRIGHTNESS, COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS

_BUNDLED_PRODUCT_JSON = Path(__file__).with_name("product.json")
_DESKTOP_PRODUCT_JSON = Path(
    "/Applications/amaran Desktop.app/Contents/Resources/config/product.json"
)
_TRAILING_MARKETING_TOKENS = {
    "ii",
    "iii",
    "iv",
    "pro",
    "max",
    "s",
}
_BATTERY_CAPABLE_PATTERNS = (
    re.compile(r"\bace\s+25c\b"),
    re.compile(r"\bpt[124]c\b"),
    re.compile(r"\bpt\s*[124]c\b"),
)
_RGB_NAME_PATTERN = re.compile(
    r"\b(?:nova|mc|mt|infinimat|infinibar)\b"
)


@dataclass(frozen=True)
class Product:
    """One product row from amaran Desktop product.json."""

    product_id: int | None
    name: str
    hex_code: str
    color_modes: tuple[str, ...]


@lru_cache(maxsize=1)
def product_catalog() -> tuple[Product, ...]:
    """Return bundled Amaran product catalog."""

    path = product_catalog_path()
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(rows, list):
        return ()

    products: list[Product] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        hex_code = _normalize_code(row.get("hex"))
        if not name and not hex_code:
            continue
        products.append(
            Product(
                product_id=_optional_int(row.get("id")),
                name=name,
                hex_code=hex_code,
                color_modes=classify_product_name(name),
            )
        )
    return tuple(products)


def product_catalog_path() -> Path:
    """Return the product catalog path used for model mapping."""

    if _BUNDLED_PRODUCT_JSON.exists():
        return _BUNDLED_PRODUCT_JSON
    return _DESKTOP_PRODUCT_JSON


def lookup_product(
    *,
    product_id: Any = None,
    code: Any = None,
    name: Any = None,
) -> Product | None:
    """Match by product_id, hex code, then fallback name."""

    products = product_catalog()
    parsed_product_id = _optional_int(product_id)
    if parsed_product_id is not None:
        for product in products:
            if product.product_id == parsed_product_id:
                return product

    normalized_code = _normalize_code(code)
    if normalized_code:
        for product in products:
            if product.hex_code == normalized_code:
                return product

    normalized_name = _normalize_name(name)
    if normalized_name:
        for product in products:
            if _normalize_name(product.name) == normalized_name:
                return product
        for product in products:
            product_name = _normalize_name(product.name)
            if product_name and (
                product_name in normalized_name or normalized_name in product_name
            ):
                return product
    return None


def classify_product_name(name: Any) -> tuple[str, ...]:
    """Classify product name into HA capability modes."""

    normalized = _normalize_name(name)
    if not normalized:
        return (COLOR_MODE_COLOR_TEMP,)
    if is_accessory_name(normalized):
        return ()

    if _is_rgb_name(normalized):
        return (COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS)
    if _is_cct_name(normalized):
        return (COLOR_MODE_COLOR_TEMP,)
    if _is_daylight_name(normalized):
        return (COLOR_MODE_BRIGHTNESS,)
    return (COLOR_MODE_COLOR_TEMP,)


def is_battery_capable_name(name: Any) -> bool:
    """Return true for known battery-powered Amaran models."""

    normalized = _normalize_name(name)
    if not normalized:
        return False
    compact = normalized.replace(" ", "")
    return any(pattern.search(normalized) or pattern.search(compact) for pattern in _BATTERY_CAPABLE_PATTERNS)


def is_accessory_name(name: Any) -> bool:
    """Return true for catalog rows that are mounts/accessories, not lights."""

    normalized = _normalize_name(name)
    if not normalized:
        return False
    return bool(re.search(r"\b(?:motorized|yoke|fresnel)\b", normalized))


def _is_rgb_name(normalized: str) -> bool:
    if _RGB_NAME_PATTERN.search(normalized):
        return True

    compact = normalized.replace(" ", "")
    if re.search(r"(?:ace|pano)?\d+c$", compact):
        return True
    if re.search(r"p\d+c$", compact):
        return True
    if re.search(r"f\d+c$", compact):
        return True
    if re.search(r"pt\d+c$", compact):
        return True
    if re.search(r"t\d+c$", compact):
        return True
    if compact.endswith("c"):
        return True
    return False


def _is_cct_name(normalized: str) -> bool:
    compact = normalized.replace(" ", "")
    return compact.endswith("x")


def _is_daylight_name(normalized: str) -> bool:
    compact = normalized.replace(" ", "")
    return compact.endswith("d")


def _normalize_name(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^0-9a-z]+", " ", text)
    tokens = [token for token in text.split() if token not in {"amaran", "aputure"}]
    while tokens and tokens[-1] in _TRAILING_MARKETING_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def _normalize_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None
