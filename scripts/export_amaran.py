#!/usr/bin/env python3
"""Export amaran Desktop mesh data as paste-ready Home Assistant JSON."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from functools import lru_cache
import glob
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

DESKTOP_DB_GLOB = (
    "~/Library/Application Support/amaran Desktop/*_secure_id/amaran.db"
)
DESKTOP_DB_FALLBACK_GLOB = (
    "~/Library/Application Support/amaran Desktop/*/amaran.db"
)
DEFAULT_SOURCE_ADDRESS = "0x000f"
DEFAULT_IV_INDEX = 0
PRODUCT_ID_COLUMNS = ("product_id", "productId", "productID", "pid")
PRODUCT_JSON_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "amaran"
    / "product.json"
)
DESKTOP_PRODUCT_JSON_PATH = Path(
    "/Applications/amaran Desktop.app/Contents/Resources/config/product.json"
)
PRODUCT_JSON_URL = (
    "https://raw.githubusercontent.com/neyako/amaran-hacs/refs/heads/main/"
    "custom_components/amaran/product.json"
)
TRAILING_MARKETING_TOKENS = {"ii", "iii", "iv", "pro", "max", "s"}


class ExportError(RuntimeError):
    """Expected export failure safe to show on stderr."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        help="amaran Desktop SQLite DB path",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--output",
        type=Path,
        help="write JSON to this path instead of stdout",
    )
    output.add_argument(
        "--stdout",
        action="store_true",
        help="write JSON to stdout (default)",
    )
    return parser.parse_args()


def desktop_db_globs(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Return macOS and Windows amaran Desktop DB glob patterns."""

    env = os.environ if env is None else env
    patterns = [
        DESKTOP_DB_GLOB,
        DESKTOP_DB_FALLBACK_GLOB,
    ]

    for variable in ("APPDATA", "LOCALAPPDATA"):
        if base := env.get(variable):
            patterns.append(
                str(Path(base) / "amaran Desktop" / "*_secure_id" / "amaran.db")
            )

    if userprofile := env.get("USERPROFILE"):
        profile = Path(userprofile)
        patterns.extend(
            str(
                profile
                / "AppData"
                / folder
                / "amaran Desktop"
                / "*_secure_id"
                / "amaran.db"
            )
            for folder in ("Roaming", "Local")
        )

    return tuple(dict.fromkeys(patterns))


def find_desktop_db(patterns: Iterable[str] | None = None) -> Path:
    patterns = desktop_db_globs() if patterns is None else tuple(patterns)
    paths = [
        Path(path)
        for pattern in patterns
        for path in glob.glob(str(Path(pattern).expanduser()))
        if Path(path).is_file()
    ]
    if not paths:
        raise ExportError("amaran Desktop database not found; pass --db PATH")
    return max(paths, key=lambda path: (path.stat().st_mtime, str(path)))


def export_payload(db_path: Path) -> dict[str, Any]:
    path = db_path.expanduser()
    if not path.is_file():
        raise ExportError("database path does not exist")

    try:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            mesh = load_mesh(conn)
            fixture_rows = load_fixture_rows(conn)
    except sqlite3.Error as err:
        raise ExportError("database could not be read") from err

    fixtures = [
        fixture
        for row in fixture_rows
        if mesh_contains_fixture(mesh, row)
        for fixture in [fixture_payload(row)]
        if fixture is not None
    ]
    if not fixtures:
        fixtures = [
            fixture
            for row in fixture_rows
            for fixture in [fixture_payload(row)]
            if fixture is not None
        ]
    if not fixtures:
        raise ExportError("no fixtures with mac_address and node_address found")

    return {
        "net_key": normalize_key(mesh["net_key"]),
        "app_key": normalize_key(mesh["app_key"]),
        "source_address": DEFAULT_SOURCE_ADDRESS,
        "iv_index": DEFAULT_IV_INDEX,
        "fixtures": fixtures,
    }


def load_mesh(conn: sqlite3.Connection) -> sqlite3.Row:
    columns = table_columns(conn, "mesh")
    if not {"net_key", "app_key"}.issubset(columns):
        raise ExportError("mesh table missing required columns")

    selected = [
        column
        for column in ("uuid", "net_key", "app_key", "fixtures_ordered_list")
        if column in columns
    ]
    order = " order by update_time desc" if "update_time" in columns else ""
    rows = conn.execute(f"select {', '.join(selected)} from mesh{order}").fetchall()
    for row in rows:
        if row["net_key"] and row["app_key"]:
            return row
    raise ExportError("mesh table has no usable keys")


def load_fixture_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    columns = table_columns(conn, "fixtures")
    if not {"mac_address", "node_address"}.issubset(columns):
        raise ExportError("fixtures table missing required columns")

    selected = [
        column
        for column in ("uuid", "mac_address", "code", "name", "node_address")
        if column in columns
    ]
    product_id_column = next(
        (column for column in PRODUCT_ID_COLUMNS if column in columns), None
    )
    if product_id_column is not None:
        selected.append(f'"{product_id_column}" as product_id')
    order = " order by node_address" if "node_address" in columns else ""
    return conn.execute(f"select {', '.join(selected)} from fixtures{order}").fetchall()


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"pragma table_info({table})").fetchall()
    if not rows:
        raise ExportError(f"{table} table not found")
    return {str(row["name"]) for row in rows}


def fixture_payload(row: sqlite3.Row) -> dict[str, Any] | None:
    mac = normalize_mac(row["mac_address"])
    node_address = optional_int(row["node_address"])
    if not mac or node_address is None:
        return None

    name = str(row["name"] or "").strip() if "name" in row.keys() else ""
    code = str(row["code"] or "").strip() if "code" in row.keys() else ""
    product_id = row["product_id"] if "product_id" in row.keys() else None
    product = lookup_catalog_product(product_id=product_id, code=code, name=name)
    model = str(product.get("name") or "Unknown") if product else "Unknown"
    capabilities = (
        catalog_capabilities(model)
        if product
        else [
            "brightness",
            "color_temp",
        ]
    )
    return {
        "name": name or f"Amaran {model}",
        "model": model,
        "mac_address": mac,
        "node_address": node_address,
        "capabilities": capabilities,
    }


def mesh_contains_fixture(mesh: sqlite3.Row, fixture: sqlite3.Row) -> bool:
    if "fixtures_ordered_list" not in mesh.keys() or not mesh["fixtures_ordered_list"]:
        return True
    ordered = str(mesh["fixtures_ordered_list"]).upper()

    tokens = []
    if "uuid" in fixture.keys() and fixture["uuid"]:
        tokens.append(str(fixture["uuid"]).upper())
    if "mac_address" in fixture.keys() and fixture["mac_address"]:
        compact_mac = re.sub(r"[^0-9A-Fa-f]", "", str(fixture["mac_address"])).upper()
        tokens.append(compact_mac)
        if "code" in fixture.keys() and fixture["code"] and len(compact_mac) >= 6:
            tokens.append(f"{str(fixture['code']).upper()}-{compact_mac[-6:]}")

    return any(token and token in ordered for token in tokens)


@lru_cache(maxsize=1)
def product_catalog() -> tuple[dict[str, Any], ...]:
    """Load the same product catalog bundled with the integration."""

    payload: Any = None
    for path in (PRODUCT_JSON_PATH, DESKTOP_PRODUCT_JSON_PATH):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            break
        except (OSError, json.JSONDecodeError):
            continue
    if payload is None:
        try:
            with urlopen(PRODUCT_JSON_URL, timeout=10) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError) as err:
            raise ExportError("product catalog could not be loaded") from err
    if not isinstance(payload, list):
        raise ExportError("product catalog has invalid data")
    return tuple(row for row in payload if isinstance(row, dict))


def lookup_catalog_product(
    *, product_id: Any = None, code: str = "", name: str = ""
) -> dict[str, Any] | None:
    """Match catalog product by id, code, then name."""

    parsed_product_id = optional_int(product_id)
    products = product_catalog()
    if parsed_product_id is not None:
        for product in products:
            if optional_int(product.get("id")) == parsed_product_id:
                return product

    normalized_code = code.strip().upper()
    if normalized_code:
        for product in products:
            if str(product.get("hex") or "").strip().upper() == normalized_code:
                return product

    exact_name = normalize_product_name(name, strip_marketing=False)
    if exact_name:
        for product in products:
            if (
                normalize_product_name(product.get("name"), strip_marketing=False)
                == exact_name
            ):
                return product

    normalized_name = normalize_product_name(name)
    if normalized_name:
        for product in products:
            product_name = normalize_product_name(product.get("name"))
            if product_name and (
                product_name in normalized_name or normalized_name in product_name
            ):
                return product
    return None


def catalog_capabilities(name: str) -> list[str]:
    """Map a catalog product name to import capabilities."""

    normalized = normalize_product_name(name)
    if re.search(r"\b(?:motorized|yoke|fresnel)\b", normalized):
        return []
    compact = normalized.replace(" ", "")
    is_rgb = (
        re.search(r"\b(?:nova|mc|mt|infinimat|infinibar)\b", normalized) is not None
        or re.search(r"(?:ace|pano)?\d+c$", compact) is not None
        or re.search(r"(?:p|f|pt|t)\d+c$", compact) is not None
        or compact.endswith("c")
    )
    if is_rgb:
        return ["brightness", "color_temp", "hs"]
    if compact.endswith("d"):
        return ["brightness"]
    return ["brightness", "color_temp"]


def normalize_product_name(value: Any, *, strip_marketing: bool = True) -> str:
    """Normalize catalog names for matching and capability classification."""

    text = re.sub(r"[^0-9a-z]+", " ", str(value or "").lower())
    tokens = [token for token in text.split() if token not in {"amaran", "aputure"}]
    if strip_marketing:
        while tokens and tokens[-1] in TRAILING_MARKETING_TOKENS:
            tokens.pop()
    return " ".join(tokens)


def normalize_key(value: Any) -> str:
    if isinstance(value, bytes):
        key = value.hex()
    else:
        key = str(value or "").strip()
    key = (
        key.removeprefix("0x")
        .removeprefix("0X")
        .replace(" ", "")
        .replace(":", "")
        .replace("-", "")
        .lower()
    )
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        raise ExportError("mesh table has invalid key data")
    return key


def normalize_mac(value: Any) -> str:
    raw = str(value or "").strip()
    compact = re.sub(r"[^0-9A-Fa-f]", "", raw)
    if len(compact) == 12:
        return ":".join(compact[index : index + 2] for index in range(0, 12, 2)).upper()
    return raw


def optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def main() -> int:
    args = parse_args()
    try:
        db_path = args.db.expanduser() if args.db else find_desktop_db()
        payload = export_payload(db_path)
        text = json.dumps(payload, indent=2) + "\n"
        if args.output:
            output_path = args.output.expanduser()
            try:
                output_path.write_text(text, encoding="utf-8")
            except OSError as err:
                raise ExportError("output file could not be written") from err
            print(f"Export written to {args.output}")
        else:
            sys.stdout.write(text)
    except ExportError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
