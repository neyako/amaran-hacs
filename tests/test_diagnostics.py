"""Diagnostics key-redaction contract tests."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import types
from typing import Any
import unittest

ROOT = Path(__file__).resolve().parents[1]
AMARAN_DIR = ROOT / "custom_components" / "amaran"
_AMARAN_MODULE_PREFIXES = ("custom_components", "custom_components.amaran")
_ORIGINAL_AMARAN_MODULES: dict[str, types.ModuleType] = {}


def _snapshot_amaran_modules() -> None:
    _ORIGINAL_AMARAN_MODULES.clear()
    for name, module in sys.modules.items():
        if name in _AMARAN_MODULE_PREFIXES or name.startswith(
            "custom_components.amaran."
        ):
            _ORIGINAL_AMARAN_MODULES[name] = module


def _restore_amaran_modules() -> None:
    for name in list(sys.modules):
        if name in _AMARAN_MODULE_PREFIXES or name.startswith(
            "custom_components.amaran."
        ):
            del sys.modules[name]
    sys.modules.update(_ORIGINAL_AMARAN_MODULES)


def tearDownModule() -> None:
    _restore_amaran_modules()


def _install_homeassistant_stubs() -> None:
    homeassistant = sys.modules.setdefault(
        "homeassistant", types.ModuleType("homeassistant")
    )
    components = sys.modules.setdefault(
        "homeassistant.components", types.ModuleType("homeassistant.components")
    )
    diagnostics = types.ModuleType("homeassistant.components.diagnostics")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = sys.modules.setdefault(
        "homeassistant.helpers", types.ModuleType("homeassistant.helpers")
    )
    storage = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.data: dict[str, Any] | None = None

        async def async_load(self) -> dict[str, Any] | None:
            return self.data

        async def async_save(self, data: dict[str, Any]) -> None:
            self.data = data

    def async_redact_data(data: Any, to_redact: Any) -> Any:
        keys = set(to_redact)

        def _redact(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: "**REDACTED**" if key in keys else _redact(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [_redact(item) for item in value]
            return value

        return _redact(data)

    diagnostics.async_redact_data = async_redact_data
    config_entries.ConfigEntry = object
    core.HomeAssistant = object
    storage.Store = Store

    sys.modules["homeassistant.components.diagnostics"] = diagnostics
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers.storage"] = storage
    sys.modules["homeassistant.helpers.event"] = types.ModuleType(
        "homeassistant.helpers.event"
    )
    homeassistant.components = components
    homeassistant.helpers = helpers


_install_homeassistant_stubs()


def _install_amaran_stubs() -> None:
    _snapshot_amaran_modules()

    custom_components = sys.modules.setdefault(
        "custom_components", types.ModuleType("custom_components")
    )
    custom_components.__path__ = [str(ROOT / "custom_components")]

    amaran = types.ModuleType("custom_components.amaran")
    amaran.__path__ = [str(AMARAN_DIR)]

    client = types.ModuleType("custom_components.amaran.client")

    class AmaranSidusClient:
        pass

    client.AmaranSidusClient = AmaranSidusClient

    sys.modules["custom_components.amaran"] = amaran
    sys.modules["custom_components.amaran.client"] = client


_install_amaran_stubs()

from custom_components.amaran.const import (  # noqa: E402
    CONF_APP_KEY,
    CONF_FIXTURES,
    CONF_NET_KEY,
    DOMAIN,
)
from custom_components.amaran.diagnostics import (  # noqa: E402
    async_get_config_entry_diagnostics,
)

_restore_amaran_modules()

NET_KEY = "00112233445566778899aabbccddeeff"
APP_KEY = "ffeeddccbbaa99887766554433221100"


def _fake_client() -> types.SimpleNamespace:
    """A client whose runtime diagnostics must never expose mesh keys."""

    return types.SimpleNamespace(
        name="Ace",
        model="Ace 25c",
        node_address=0x000B,
        source_address=0x000F,
        supported_color_modes=("color_temp", "hs"),
        sequence=100001,
        connected=True,
        transport_state="proxy_ready",
        last_connect_time=1.0,
        last_write_latency_ms=12.5,
        transport_mode="persistent",
        proxy_selection="auto",
        proxy_address="",
        fixture_reachable=True,
        fixture_stale_seconds=None,
        presence_checking_enabled=False,
        presence_unavailable_after=120.0,
        last_advertisement_seen=None,
        last_advertisement_address=None,
        last_advertisement_rssi=None,
        last_proxy_advertisement_seen=None,
        desired_power=True,
        desired_brightness=200,
        desired_color_temp_kelvin=5000,
        desired_hs_color=None,
        desired_active_color_mode="color_temp",
        last_bluetooth_device=None,
        last_write=None,
        last_command=None,
        last_physical_validation=None,
        # Present on the real client; must NOT reach diagnostics output.
        transport_metrics={"state": "proxy_ready", "last_write_time": None},
        data={CONF_NET_KEY: NET_KEY, CONF_APP_KEY: APP_KEY},
    )


class DiagnosticsRedactionTest(unittest.IsolatedAsyncioTestCase):
    def _entry(self) -> types.SimpleNamespace:
        # Keys at top level AND nested inside a fixtures list (both must redact).
        return types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "name": "Ace",
                CONF_NET_KEY: NET_KEY,
                CONF_APP_KEY: APP_KEY,
                CONF_FIXTURES: [
                    {"name": "Ace", CONF_NET_KEY: NET_KEY, CONF_APP_KEY: APP_KEY}
                ],
            },
        )

    async def test_entry_section_redacts_top_level_and_nested_keys(self) -> None:
        hass = types.SimpleNamespace(data={DOMAIN: {"entry-1": [_fake_client()]}})
        result = await async_get_config_entry_diagnostics(hass, self._entry())

        entry = result["entry"]
        self.assertEqual(entry[CONF_NET_KEY], "**REDACTED**")
        self.assertEqual(entry[CONF_APP_KEY], "**REDACTED**")
        nested = entry[CONF_FIXTURES][0]
        self.assertEqual(nested[CONF_NET_KEY], "**REDACTED**")
        self.assertEqual(nested[CONF_APP_KEY], "**REDACTED**")

    async def test_raw_keys_never_appear_anywhere_in_output(self) -> None:
        hass = types.SimpleNamespace(data={DOMAIN: {"entry-1": [_fake_client()]}})
        result = await async_get_config_entry_diagnostics(hass, self._entry())

        serialized = json.dumps(result)
        self.assertNotIn(NET_KEY, serialized)
        self.assertNotIn(APP_KEY, serialized)

    async def test_runtime_section_present_and_key_free(self) -> None:
        hass = types.SimpleNamespace(data={DOMAIN: {"entry-1": [_fake_client()]}})
        result = await async_get_config_entry_diagnostics(hass, self._entry())

        self.assertEqual(len(result["runtime"]), 1)
        self.assertEqual(result["runtime"][0]["name"], "Ace")
        self.assertNotIn(NET_KEY, json.dumps(result["runtime"]))
        self.assertNotIn(APP_KEY, json.dumps(result["runtime"]))


if __name__ == "__main__":
    unittest.main()
