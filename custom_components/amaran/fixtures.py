"""Fixture import and capability detection helpers."""

from __future__ import annotations

from dataclasses import dataclass
import glob
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .const import (
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_HS,
    CONF_ADDRESS,
    CONF_APP_KEY,
    CONF_BATTERY_CAPABLE,
    CONF_BATTERY_PERCENTAGE,
    CONF_BLE_MAC,
    CONF_DEVICE_UUID,
    CONF_FIXTURE_CATALOG,
    CONF_FIXTURE_CODE,
    CONF_FIXTURES,
    CONF_IMPORT_JSON,
    CONF_IMPORT_METHOD,
    CONF_IMPORT_PATH,
    CONF_MESH_UUID,
    CONF_MODEL,
    CONF_NAME,
    CONF_NET_KEY,
    CONF_NODE_ADDRESS,
    CONF_PRODUCT_ID,
    CONF_SELECTED_FIXTURE,
    CONF_SELECTED_FIXTURE_IDS,
    CONF_SETUP_METHOD,
    CONF_SUPPORTED_COLOR_MODES,
)
from .product_catalog import (
    classify_product_name,
    is_battery_capable_name,
    lookup_product,
)
from .protocol import normalize_hex_key

_DESKTOP_DB_GLOB = (
    "~/Library/Application Support/amaran Desktop/*_secure_id/amaran.db"
)
_DESKTOP_DB_FALLBACK_GLOB = "~/Library/Application Support/amaran Desktop/*/amaran.db"

_CODE_PROFILES = {
    "400O5": ("100x", (COLOR_MODE_COLOR_TEMP,)),
    "400M5": ("60x S", (COLOR_MODE_COLOR_TEMP,)),
    "400U5": ("Ace 25c", (COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS)),
    "400W5": ("Pano 60c", (COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS)),
}
_PRODUCT_ID_COLUMNS = (CONF_PRODUCT_ID, "productId", "productID", "pid")


@dataclass(frozen=True)
class FixtureProfile:
    """Fixture model and supported Home Assistant color modes."""

    model: str
    color_modes: tuple[str, ...]

    @property
    def supported(self) -> bool:
        """Return true when the fixture has a known command surface."""

        return bool(self.color_modes)

    @property
    def supports_hs(self) -> bool:
        """Return true when the fixture supports HSI/color commands."""

        return COLOR_MODE_HS in self.color_modes


@dataclass(frozen=True)
class FixtureImport:
    """Imported fixture collection plus skipped row details."""

    fixtures: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    source_path: str


def default_desktop_db_path() -> str:
    """Return the first amaran Desktop DB path if one exists."""

    for pattern in (_DESKTOP_DB_GLOB, _DESKTOP_DB_FALLBACK_GLOB):
        for path in sorted(glob.glob(str(Path(pattern).expanduser()))):
            if Path(path).is_file():
                return path
    return ""


def load_fixture_import(path: str | Path) -> FixtureImport:
    """Load supported fixtures from an amaran Desktop DB or exported JSON."""

    source = Path(str(path)).expanduser()
    if not source.exists():
        raise ValueError(CONF_IMPORT_PATH)

    try:
        if source.suffix.lower() == ".json":
            fixtures, skipped = _load_json(source)
        else:
            fixtures, skipped = _load_sqlite(source)
    except (json.JSONDecodeError, sqlite3.Error) as err:
        raise ValueError(CONF_IMPORT_PATH) from err
    if not fixtures:
        raise ValueError("fixtures")
    return FixtureImport(
        fixtures=fixtures,
        skipped=skipped,
        source_path=str(source),
    )


def load_fixture_import_json(json_text: str) -> FixtureImport:
    """Load supported fixtures from pasted JSON text."""

    try:
        payload = json.loads(json_text)
        fixtures, skipped = _load_json_payload(payload)
    except json.JSONDecodeError as err:
        raise ValueError(CONF_IMPORT_JSON) from err
    if not fixtures:
        raise ValueError("fixtures")
    return FixtureImport(fixtures=fixtures, skipped=skipped, source_path="pasted_json")


def detect_fixture_profile(
    *,
    name: str | None = None,
    model: str | None = None,
    code: str | None = None,
    product_id: Any = None,
) -> FixtureProfile:
    """Classify a fixture into supported HA color modes."""

    product = lookup_product(
        product_id=product_id,
        code=code,
        name=model or name,
    )
    if product is not None:
        return FixtureProfile(product.name, product.color_modes)

    normalized_code = str(code or "").strip().upper()
    if normalized_code in _CODE_PROFILES:
        profile_model, color_modes = _CODE_PROFILES[normalized_code]
        return FixtureProfile(profile_model, color_modes)

    text = _normalize_model_text(" ".join(value or "" for value in (model, name)))
    if text:
        modes = classify_product_name(text)
        return FixtureProfile(str(model or name or "Unknown").strip(), modes)
    return FixtureProfile(
        str(model or code or "Unknown").strip() or "Unknown",
        (COLOR_MODE_COLOR_TEMP,),
    )


def supported_color_modes_for_fixture(data: dict[str, Any]) -> tuple[str, ...]:
    """Return final color modes from DB/import data with known-model overrides."""

    product = lookup_product(
        product_id=data.get(CONF_PRODUCT_ID),
        code=data.get(CONF_FIXTURE_CODE),
        name=data.get(CONF_MODEL) or data.get(CONF_NAME),
    )
    if product is not None:
        return product.color_modes

    profile = detect_fixture_profile(
        name=data.get(CONF_NAME),
        model=data.get(CONF_MODEL),
        code=data.get(CONF_FIXTURE_CODE),
        product_id=data.get(CONF_PRODUCT_ID),
    )
    if profile.color_modes != (COLOR_MODE_COLOR_TEMP,):
        return profile.color_modes

    explicit_modes = _explicit_color_modes(data)
    if explicit_modes:
        return explicit_modes
    return profile.color_modes


def fixture_unique_id(data: dict[str, Any]) -> str:
    """Return a stable fixture identifier for config flow and entity IDs."""

    for field in (CONF_BLE_MAC,):
        if value := data.get(field):
            return _normalize_identifier(str(value))
    address = str(data.get(CONF_ADDRESS) or "")
    if len(re.sub(r"[^0-9a-fA-F]", "", address)) == 12:
        return _normalize_identifier(_normalize_mac(address))
    if value := data.get(CONF_DEVICE_UUID):
        return _normalize_identifier(str(value))
    mesh_uuid = _normalize_identifier(str(data.get(CONF_MESH_UUID) or "mesh"))
    node_address = int(data[CONF_NODE_ADDRESS])
    return f"{mesh_uuid}_node_{node_address:04x}"


def fixture_device_identifier(data: dict[str, Any]) -> str:
    """Return a fixture-specific Home Assistant device identifier."""

    address = str(data.get(CONF_BLE_MAC) or data.get(CONF_ADDRESS) or "")
    compact_address = re.sub(r"[^0-9a-fA-F]", "", address)
    if len(compact_address) == 12:
        return _normalize_mac(address)
    return fixture_unique_id(data)


def fixture_entry_data(
    import_data: dict[str, Any], fixture: dict[str, Any]
) -> dict[str, Any]:
    """Build one direct fixture config entry from imported mesh data."""

    data = {**import_data, **fixture}
    for key in (
        CONF_FIXTURE_CATALOG,
        CONF_FIXTURES,
        CONF_IMPORT_JSON,
        CONF_IMPORT_METHOD,
        CONF_IMPORT_PATH,
        CONF_SELECTED_FIXTURE,
        CONF_SELECTED_FIXTURE_IDS,
        CONF_SETUP_METHOD,
    ):
        data.pop(key, None)
    return data


def fixture_selection_choices(fixtures: list[dict[str, Any]]) -> dict[str, str]:
    """Return config-flow choices keyed by stable fixture ID."""

    choices: dict[str, str] = {}
    for fixture in fixtures:
        fixture_id = fixture_unique_id(fixture)
        name = str(fixture.get(CONF_NAME) or "Amaran light")
        model = str(fixture.get(CONF_MODEL) or "Unknown")
        capabilities = ", ".join(light_capability_names(fixture))
        choices[fixture_id] = f"{name} ({model}) - {capabilities}"
    return choices


def light_capability_names(data: dict[str, Any]) -> tuple[str, ...]:
    """Return user-friendly capability names for one imported light."""

    modes = supported_color_modes_for_fixture(data)
    capabilities = ["Brightness"]
    if COLOR_MODE_COLOR_TEMP in modes:
        capabilities.append("Color temperature")
    if COLOR_MODE_HS in modes:
        capabilities.append("Color/HSI")
    if is_battery_capable_light(data):
        capabilities.append("Battery")
    return tuple(capabilities)


def is_battery_capable_light(data: dict[str, Any]) -> bool:
    """Return true when model/catalog data marks this light battery-powered."""

    explicit = data.get(CONF_BATTERY_CAPABLE)
    if isinstance(explicit, bool):
        return explicit
    model = data.get(CONF_MODEL) or data.get(CONF_NAME) or ""
    return is_battery_capable_name(model)


def fixture_for_unique_id(
    fixtures: list[dict[str, Any]], fixture_id: str
) -> dict[str, Any] | None:
    """Return one fixture from a catalog by stable ID."""

    return next(
        (fixture for fixture in fixtures if fixture_unique_id(fixture) == fixture_id),
        None,
    )


def _load_sqlite(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        mesh_rows = conn.execute(
            """
            select uuid, net_key, app_key, fixtures_ordered_list, update_time
            from mesh
            order by update_time desc
            """
        ).fetchall()
        if not mesh_rows:
            raise ValueError("mesh")

        fixture_rows = conn.execute(_fixture_select_sql(conn)).fetchall()
    finally:
        conn.close()

    fixtures: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in fixture_rows:
        mac = str(row["mac_address"] or "").strip()
        node_address = _optional_int(row["node_address"])
        code = str(row["code"] or "").strip()
        name = str(row["name"] or "").strip()
        product_id = _row_value(row, CONF_PRODUCT_ID)
        if not mac or node_address is None or node_address <= 1:
            skipped.append({"name": name, "code": code, "reason": "missing_address"})
            continue

        profile = detect_fixture_profile(name=name, code=code, product_id=product_id)
        if not profile.supported:
            skipped.append({"name": name, "code": code, "reason": "unsupported"})
            continue

        mesh = _mesh_for_fixture(mesh_rows, row)
        fixture = _fixture_data(
            net_key=mesh["net_key"],
            app_key=mesh["app_key"],
            mesh_uuid=mesh["uuid"],
            mac=mac,
            node_address=node_address,
            name=name or f"Amaran {profile.model}",
            model=profile.model,
            code=code,
            product_id=product_id,
            device_uuid=row["device_uuid"] or row["uuid"],
            color_modes=supported_color_modes_for_fixture(
                {
                    CONF_NAME: name,
                    CONF_MODEL: profile.model,
                    CONF_FIXTURE_CODE: code,
                    CONF_PRODUCT_ID: product_id,
                }
            ),
        )
        fixtures.append(fixture)
    return fixtures, skipped


def _load_json(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _load_json_payload(payload)


def _load_json_payload(payload: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError(CONF_IMPORT_PATH)

    raw_fixtures = payload.get(CONF_FIXTURES)
    if raw_fixtures is None:
        raw_fixtures = payload.get("lights")
    if not isinstance(raw_fixtures, list):
        raise ValueError("fixtures")

    net_key = payload.get(CONF_NET_KEY) or payload.get("netKey")
    app_key = payload.get(CONF_APP_KEY) or payload.get("appKey")
    mesh_uuid = payload.get(CONF_MESH_UUID) or payload.get("meshUuid") or "json"
    fixtures: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_fixtures):
        if not isinstance(raw, dict):
            skipped.append({"index": index, "reason": "invalid_fixture"})
            continue

        item_net_key = raw.get(CONF_NET_KEY) or raw.get("netKey") or net_key
        item_app_key = raw.get(CONF_APP_KEY) or raw.get("appKey") or app_key
        mac = raw.get(CONF_BLE_MAC) or raw.get("mac_address") or raw.get("mac")
        node_address = _optional_int(
            raw.get(CONF_NODE_ADDRESS) or raw.get("address") or raw.get("node")
        )
        code = raw.get(CONF_FIXTURE_CODE) or raw.get("code")
        name = raw.get(CONF_NAME) or raw.get("name")
        model = raw.get(CONF_MODEL) or raw.get("model")
        product_id = raw.get(CONF_PRODUCT_ID) or raw.get("productId")
        explicit_modes = _explicit_color_modes(raw)
        battery_value = (
            raw.get(CONF_BATTERY_PERCENTAGE)
            if CONF_BATTERY_PERCENTAGE in raw
            else raw.get("battery_percentage")
        )
        if not item_net_key or not item_app_key or not mac or node_address is None:
            skipped.append({"name": name, "code": code, "reason": "missing_address"})
            continue

        profile = detect_fixture_profile(
            name=name,
            model=model,
            code=code,
            product_id=product_id,
        )
        color_modes = supported_color_modes_for_fixture(
            {
                CONF_NAME: name,
                CONF_MODEL: model,
                CONF_FIXTURE_CODE: code,
                CONF_PRODUCT_ID: product_id,
                CONF_SUPPORTED_COLOR_MODES: explicit_modes,
            }
        )

        fixtures.append(
            _fixture_data(
                net_key=item_net_key,
                app_key=item_app_key,
                mesh_uuid=raw.get(CONF_MESH_UUID) or raw.get("meshUuid") or mesh_uuid,
                mac=str(mac),
                node_address=node_address,
                name=str(name or f"Amaran {profile.model}"),
                model=profile.model,
                code=str(code or ""),
                product_id=product_id,
                device_uuid=raw.get(CONF_DEVICE_UUID) or raw.get("uuid"),
                color_modes=color_modes,
                battery_capable=_raw_battery_capable(raw, model or profile.model),
                battery_percentage=_optional_int(battery_value),
            )
        )
    return fixtures, skipped


def _fixture_select_sql(conn: sqlite3.Connection) -> str:
    columns = {row[1] for row in conn.execute("pragma table_info(fixtures)").fetchall()}
    selected = [
        "uuid",
        "mac_address",
        "code",
        "name",
        "node_address",
        "device_uuid",
        "state",
    ]
    product_id_column = next(
        (column for column in _PRODUCT_ID_COLUMNS if column in columns), None
    )
    if product_id_column is not None:
        selected.append(f'"{product_id_column}" as {CONF_PRODUCT_ID}')
    return f"select {', '.join(selected)} from fixtures order by node_address"


def _fixture_data(
    *,
    net_key: Any,
    app_key: Any,
    mesh_uuid: Any,
    mac: str,
    node_address: int,
    name: str,
    model: str,
    code: str,
    product_id: Any,
    device_uuid: Any,
    color_modes: tuple[str, ...],
    battery_capable: bool | None = None,
    battery_percentage: int | None = None,
) -> dict[str, Any]:
    battery_capable = (
        is_battery_capable_name(model) if battery_capable is None else battery_capable
    )
    return {
        CONF_ADDRESS: _normalize_mac(mac),
        CONF_BLE_MAC: _normalize_mac(mac),
        CONF_NODE_ADDRESS: int(node_address),
        CONF_NAME: name.strip() or f"Amaran {model}",
        CONF_MODEL: model,
        CONF_FIXTURE_CODE: code,
        CONF_PRODUCT_ID: _optional_int(product_id),
        CONF_DEVICE_UUID: str(device_uuid or ""),
        CONF_MESH_UUID: str(mesh_uuid or ""),
        CONF_NET_KEY: normalize_hex_key(str(net_key), field="network key").hex(),
        CONF_APP_KEY: normalize_hex_key(str(app_key), field="app key").hex(),
        CONF_SUPPORTED_COLOR_MODES: list(color_modes),
        CONF_BATTERY_CAPABLE: bool(battery_capable),
        CONF_BATTERY_PERCENTAGE: _clamp_battery(battery_percentage),
    }


def _mesh_for_fixture(mesh_rows: list[sqlite3.Row], fixture: sqlite3.Row) -> sqlite3.Row:
    if len(mesh_rows) == 1:
        return mesh_rows[0]

    code = str(fixture["code"] or "")
    mac_suffix = str(fixture["mac_address"] or "")[-8:].replace(":", "").upper()
    token = f"{code}-{mac_suffix}"
    for mesh in mesh_rows:
        ordered = str(mesh["fixtures_ordered_list"] or "").upper()
        if token.upper() in ordered or str(fixture["uuid"]).upper() in ordered:
            return mesh
    return mesh_rows[0]


def _row_value(row: sqlite3.Row, key: str) -> Any:
    return row[key] if key in row.keys() else None


def _normalize_model_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("-", " ")).strip().lower()


def _explicit_color_modes(raw: dict[str, Any]) -> tuple[str, ...]:
    value = (
        raw.get(CONF_SUPPORTED_COLOR_MODES)
        or raw.get("supportedColorModes")
        or raw.get("color_modes")
        or raw.get("colorModes")
        or raw.get("capabilities")
    )
    if value is None:
        return ()
    if isinstance(value, str):
        tokens = re.split(r"[,|\s]+", value.strip().lower())
    elif isinstance(value, dict):
        tokens = [str(key).lower() for key, enabled in value.items() if enabled]
    elif isinstance(value, (list, tuple, set)):
        tokens = [str(item).lower() for item in value]
    else:
        return ()

    modes = [COLOR_MODE_COLOR_TEMP]
    if any(token in {"brightness", "bright", "d", "daylight"} for token in tokens):
        modes = [COLOR_MODE_BRIGHTNESS]
    if any(token in {"hs", "hsi", "rgb", "color", "colour", "c"} for token in tokens):
        modes.append(COLOR_MODE_HS)
    return tuple(dict.fromkeys(modes))


def _normalize_mac(value: str) -> str:
    compact = re.sub(r"[^0-9a-fA-F]", "", value)
    if len(compact) == 12:
        return ":".join(compact[index : index + 2] for index in range(0, 12, 2)).upper()
    return value.strip()


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", value.strip().lower()).strip("_")


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def _raw_battery_capable(raw: dict[str, Any], model: Any) -> bool:
    explicit = raw.get(CONF_BATTERY_CAPABLE)
    if isinstance(explicit, bool):
        return explicit
    capabilities = raw.get("capabilities")
    if isinstance(capabilities, dict) and isinstance(capabilities.get("battery"), bool):
        return bool(capabilities["battery"])
    return is_battery_capable_name(model)


def _clamp_battery(value: int | None) -> int | None:
    if value is None:
        return None
    return max(0, min(100, int(value)))
