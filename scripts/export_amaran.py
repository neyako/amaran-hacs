#!/usr/bin/env python3
"""Export amaran Desktop mesh data as paste-ready Home Assistant JSON."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
import glob
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

DESKTOP_DB_GLOB = (
    "~/Library/Application Support/amaran Desktop/*_secure_id/amaran.db"
)
DESKTOP_DB_FALLBACK_GLOB = (
    "~/Library/Application Support/amaran Desktop/*/amaran.db"
)
DEFAULT_SOURCE_ADDRESS = "0x000f"
DEFAULT_IV_INDEX = 0

CAPABILITIES_BICOLOR = ["brightness", "color_temp"]
CAPABILITIES_COLOR = ["brightness", "color_temp", "hs"]

CODE_MODELS = {
    "400O5": "100x",
    "400M5": "60x S",
    "400U5": "Ace 25c",
    "400W5": "Pano 60c",
}


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
    model = infer_model(name=name, code=code)
    return {
        "name": name or f"Amaran {model}",
        "model": model,
        "mac_address": mac,
        "node_address": node_address,
        "capabilities": infer_capabilities(model),
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


def infer_model(*, name: str, code: str) -> str:
    normalized_code = code.strip().upper()
    if normalized_code in CODE_MODELS:
        return CODE_MODELS[normalized_code]

    text = normalize_model_text(name)
    if "ace 25c" in text:
        return "Ace 25c"
    if "pano 60c" in text:
        return "Pano 60c"
    if re.search(r"\b100x(?:\s+s)?\b", text):
        return "100x"
    if re.search(r"\b60x\s+s\b", text):
        return "60x S"
    return "Unknown"


def infer_capabilities(model: str) -> list[str]:
    text = normalize_model_text(model)
    if "ace 25c" in text or "pano 60c" in text:
        return list(CAPABILITIES_COLOR)
    if re.search(r"\b100x(?:\s+s)?\b", text) or re.search(r"\b60x\s+s\b", text):
        return list(CAPABILITIES_BICOLOR)
    return list(CAPABILITIES_BICOLOR)


def normalize_model_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("-", " ")).strip().lower()


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
