"""Diagnostics support for Amaran Sidus."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .client import AmaranSidusClient
from .const import CONF_APP_KEY, CONF_NET_KEY, DOMAIN
from .product_catalog import product_catalog, product_catalog_path
from .redaction import redact_sensitive

TO_REDACT = [CONF_APP_KEY, CONF_NET_KEY]
_BRAND_DIR = Path(__file__).with_name("brand")
_BRAND_FILES = (
    "icon.png",
    "logo.png",
    "dark_icon.png",
    "dark_logo.png",
    "icon@2x.png",
    "logo@2x.png",
    "dark_icon@2x.png",
    "dark_logo@2x.png",
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    stored_clients = hass.data.get(DOMAIN, {}).get(entry.entry_id) or []
    if isinstance(stored_clients, AmaranSidusClient):
        clients = [stored_clients]
    else:
        clients = list(stored_clients)
    return {
        "entry": async_redact_data(redact_sensitive(dict(entry.data)), TO_REDACT),
        "branding": _branding_diagnostics(),
        "model_mapping": _model_mapping_diagnostics(),
        "runtime": [_client_diagnostics(client) for client in clients],
    }


def _client_diagnostics(client: AmaranSidusClient) -> dict[str, Any]:
    return {
        "name": client.name,
        "model": client.model,
        "node_address": client.node_address,
        "source_address": client.source_address,
        "supported_color_modes": list(client.supported_color_modes),
        "current_sequence": client.sequence,
        "connected": client.connected,
        "transport_state": client.transport_state,
        "last_connect_time": client.last_connect_time,
        "last_write_latency_ms": client.last_write_latency_ms,
        "last_write_time": client.transport_metrics.get("last_write_time"),
        "connection_mode": client.transport_mode,
        "connection_selection": client.proxy_selection,
        "connection_address": client.proxy_address,
        "light_reachable": client.fixture_reachable,
        "light_stale_seconds": client.fixture_stale_seconds,
        "light_advertisement_availability": client.presence_checking_enabled,
        "light_stale_after_seconds": client.presence_unavailable_after,
        "last_advertisement_seen": client.last_advertisement_seen,
        "last_advertisement_address": client.last_advertisement_address,
        "last_advertisement_rssi": client.last_advertisement_rssi,
        "last_connection_advertisement_seen": client.last_proxy_advertisement_seen,
        "transport_metrics": client.transport_metrics,
        "cached_state": {
            "power": client.desired_power,
            "brightness": client.desired_brightness,
            "cct": client.desired_color_temp_kelvin,
            "hs": client.desired_hs_color,
            "active_color_mode": client.desired_active_color_mode,
        },
        "last_bluetooth_device": client.last_bluetooth_device,
        "last_write": client.last_write,
        "last_command": client.last_command,
        "last_physical_validation": client.last_physical_validation,
    }


def _branding_diagnostics() -> dict[str, Any]:
    detected_files = {
        filename: str(path)
        for filename in _BRAND_FILES
        if (path := _BRAND_DIR / filename).is_file()
    }
    return {
        "brand_dir": str(_BRAND_DIR),
        "detected_files": detected_files,
        "icon_path": detected_files.get("icon.png"),
        "logo_path": detected_files.get("logo.png"),
    }


def _model_mapping_diagnostics() -> dict[str, Any]:
    products = product_catalog()
    return {
        "source_path": str(product_catalog_path()),
        "loaded_count": len(products),
        "products": [
            {
                "product_id": product.product_id,
                "name": product.name,
                "hex_code": product.hex_code,
                "color_modes": list(product.color_modes),
            }
            for product in products
        ],
    }
