"""Green/magenta number entity tests."""

from __future__ import annotations

from enum import Enum
import sys
import types
from typing import Any
import unittest


def _install_number_stubs() -> None:
    homeassistant = sys.modules.setdefault(
        "homeassistant", types.ModuleType("homeassistant")
    )
    components = sys.modules.setdefault(
        "homeassistant.components", types.ModuleType("homeassistant.components")
    )
    number = types.ModuleType("homeassistant.components.number")
    config_entries = sys.modules.setdefault(
        "homeassistant.config_entries", types.ModuleType("homeassistant.config_entries")
    )
    core = sys.modules.setdefault(
        "homeassistant.core", types.ModuleType("homeassistant.core")
    )
    helpers = sys.modules.setdefault(
        "homeassistant.helpers", types.ModuleType("homeassistant.helpers")
    )
    storage = sys.modules.setdefault(
        "homeassistant.helpers.storage",
        types.ModuleType("homeassistant.helpers.storage"),
    )
    device_registry = sys.modules.setdefault(
        "homeassistant.helpers.device_registry",
        types.ModuleType("homeassistant.helpers.device_registry"),
    )
    entity = types.ModuleType("homeassistant.helpers.entity")
    entity_platform = sys.modules.setdefault(
        "homeassistant.helpers.entity_platform",
        types.ModuleType("homeassistant.helpers.entity_platform"),
    )

    class NumberEntity:
        def async_write_ha_state(self) -> None:
            self._write_count = getattr(self, "_write_count", 0) + 1

    class RestoreNumber:
        async def async_added_to_hass(self) -> None:
            return None

        async def async_get_last_number_data(self) -> Any:
            return None

    class NumberMode(str, Enum):
        SLIDER = "slider"

    class EntityCategory(str, Enum):
        CONFIG = "config"

    class Store:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.data: dict[str, Any] | None = None

        async def async_load(self) -> dict[str, Any] | None:
            return self.data

        async def async_save(self, data: dict[str, Any]) -> None:
            self.data = data

    number.NumberEntity = NumberEntity
    number.NumberMode = NumberMode
    number.RestoreNumber = RestoreNumber
    config_entries.ConfigEntry = object
    core.HomeAssistant = object
    storage.Store = Store
    device_registry.CONNECTION_BLUETOOTH = "bluetooth"
    entity.EntityCategory = EntityCategory
    entity_platform.AddEntitiesCallback = object

    sys.modules["homeassistant.components.number"] = number
    sys.modules["homeassistant.helpers.entity"] = entity
    homeassistant.components = components
    homeassistant.helpers = helpers


_install_number_stubs()

from custom_components.amaran.const import CONF_BLE_MAC, CONF_NODE_ADDRESS, DOMAIN
import custom_components.amaran.number as number_module
from custom_components.amaran.number import AmaranGreenMagentaNumber


class GreenMagentaNumberTest(unittest.IsolatedAsyncioTestCase):
    async def test_native_value_reflects_client_green_magenta(self) -> None:
        client = FakeClient(green_magenta=-2)
        entity = AmaranGreenMagentaNumber(client)

        self.assertEqual(entity.native_value, -2.0)

    async def test_set_native_value_delegates_to_client(self) -> None:
        client = FakeClient()
        entity = AmaranGreenMagentaNumber(client)

        await entity.async_set_native_value(3.0)

        self.assertEqual(client.set_values, [3])
        self.assertEqual(entity._write_count, 1)

    async def test_setup_entry_creates_only_cct_numbers(self) -> None:
        cct_client = FakeClient(supports_color_temp=True)
        brightness_client = FakeClient(supports_color_temp=False)
        hass = types.SimpleNamespace(
            data={DOMAIN: {"entry-1": [cct_client, brightness_client]}}
        )
        entry = types.SimpleNamespace(entry_id="entry-1")
        added: list[Any] = []

        def _add_entities(entities: Any) -> None:
            added.extend(list(entities))

        await number_module.async_setup_entry(hass, entry, _add_entities)

        self.assertEqual(len(added), 1)
        self.assertIs(added[0]._client, cct_client)


class FakeClient:
    address = "AA:BB:CC:DD:EE:01"
    ble_mac = address
    node_address = 0x000B
    source_address = 0x000F
    name = "Ace"
    model = "Ace 25c"
    is_available = True
    data = {
        CONF_BLE_MAC: ble_mac,
        CONF_NODE_ADDRESS: node_address,
    }

    def __init__(
        self, *, green_magenta: int = 0, supports_color_temp: bool = True
    ) -> None:
        self.green_magenta = green_magenta
        self.supports_color_temp = supports_color_temp
        self.set_values: list[int] = []

    async def async_set_green_magenta(self, gm: int) -> None:
        self.set_values.append(gm)

    def set_green_magenta_cached(self, gm: int) -> None:
        self.green_magenta = gm


if __name__ == "__main__":
    unittest.main()
