"""Transport diagnostic sensor UX tests."""

from __future__ import annotations

from enum import Enum
import sys
import types
from typing import Any
import unittest


def _install_sensor_stubs() -> None:
    homeassistant = sys.modules.setdefault(
        "homeassistant", types.ModuleType("homeassistant")
    )
    components = sys.modules.setdefault(
        "homeassistant.components", types.ModuleType("homeassistant.components")
    )
    sensor = types.ModuleType("homeassistant.components.sensor")
    config_entries = sys.modules.setdefault(
        "homeassistant.config_entries", types.ModuleType("homeassistant.config_entries")
    )
    const = types.ModuleType("homeassistant.const")
    core = sys.modules.setdefault(
        "homeassistant.core", types.ModuleType("homeassistant.core")
    )
    helpers = sys.modules.setdefault(
        "homeassistant.helpers", types.ModuleType("homeassistant.helpers")
    )
    device_registry = sys.modules.setdefault(
        "homeassistant.helpers.device_registry",
        types.ModuleType("homeassistant.helpers.device_registry"),
    )
    entity = types.ModuleType("homeassistant.helpers.entity")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    entity_platform = sys.modules.setdefault(
        "homeassistant.helpers.entity_platform",
        types.ModuleType("homeassistant.helpers.entity_platform"),
    )

    class SensorEntity:
        pass

    class EntityCategory(str, Enum):
        DIAGNOSTIC = "diagnostic"

    class SensorDeviceClass(str, Enum):
        BATTERY = "battery"

    class SensorStateClass(str, Enum):
        MEASUREMENT = "measurement"

    class RegistryEntryDisabler(str, Enum):
        INTEGRATION = "integration"

    sensor.SensorEntity = SensorEntity
    sensor.SensorDeviceClass = SensorDeviceClass
    sensor.SensorStateClass = SensorStateClass
    config_entries.ConfigEntry = object
    const.PERCENTAGE = "%"
    core.HomeAssistant = object
    device_registry.CONNECTION_BLUETOOTH = "bluetooth"
    entity.EntityCategory = EntityCategory
    entity_registry.RegistryEntryDisabler = RegistryEntryDisabler
    entity_registry.async_get = lambda hass: None
    entity_platform.AddEntitiesCallback = object

    sys.modules["homeassistant.components.sensor"] = sensor
    sys.modules["homeassistant.const"] = const
    sys.modules["homeassistant.helpers.entity"] = entity
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry
    homeassistant.components = components
    homeassistant.helpers = helpers


_install_sensor_stubs()

from custom_components.amaran.const import CONF_BLE_MAC, CONF_NODE_ADDRESS, DOMAIN
import custom_components.amaran.sensor as sensor_module
from custom_components.amaran.sensor import (
    AmaranSidusBatterySensor,
    AmaranSidusTransportSensor,
    async_disable_transport_sensors,
)


class TransportSensorUxTest(unittest.TestCase):
    def test_transport_sensor_is_diagnostic_and_disabled_by_default(self) -> None:
        self.assertEqual(
            AmaranSidusTransportSensor._attr_entity_category.value,
            "diagnostic",
        )
        self.assertFalse(
            AmaranSidusTransportSensor._attr_entity_registry_enabled_default
        )


class BatterySensorTest(unittest.TestCase):
    def test_battery_sensor_is_diagnostic_and_enabled_by_default(self) -> None:
        self.assertEqual(AmaranSidusBatterySensor._attr_entity_category.value, "diagnostic")
        self.assertTrue(AmaranSidusBatterySensor._attr_entity_registry_enabled_default)
        self.assertEqual(AmaranSidusBatterySensor._attr_device_class.value, "battery")
        self.assertEqual(AmaranSidusBatterySensor._attr_state_class.value, "measurement")

    def test_battery_sensor_unavailable_when_unknown(self) -> None:
        client = FakeClient()
        client.battery_percentage = None
        sensor = AmaranSidusBatterySensor(client)

        self.assertIsNone(sensor.native_value)
        self.assertFalse(sensor.available)

    def test_battery_sensor_uses_real_value_when_known(self) -> None:
        client = FakeClient()
        client.battery_percentage = 73
        sensor = AmaranSidusBatterySensor(client)

        self.assertEqual(sensor.native_value, 73)
        self.assertTrue(sensor.available)


class SensorSetupTest(unittest.IsolatedAsyncioTestCase):
    async def test_battery_sensor_created_only_for_battery_capable_lights(self) -> None:
        battery_client = FakeClient()
        battery_client.battery_capable = True
        plug_client = FakeClient()
        plug_client.battery_capable = False
        hass = types.SimpleNamespace(
            data={DOMAIN: {"entry-1": [battery_client, plug_client]}}
        )
        entry = types.SimpleNamespace(entry_id="entry-1")
        added: list[Any] = []

        def _add_entities(entities: list[Any]) -> None:
            added.extend(entities)

        await sensor_module.async_setup_entry(hass, entry, _add_entities)

        self.assertEqual(
            sum(isinstance(entity, AmaranSidusBatterySensor) for entity in added),
            1,
        )


class ExistingTransportSensorMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_existing_transport_sensor_is_integration_disabled(self) -> None:
        registry = FakeRegistry()
        sensor_module.er.async_get = lambda hass: registry
        hass = types.SimpleNamespace(
            data={DOMAIN: {"entry-1": [FakeClient()]}}
        )
        entry = types.SimpleNamespace(entry_id="entry-1")
        await async_disable_transport_sensors(hass, hass.data[DOMAIN][entry.entry_id])

        self.assertEqual(
            registry.lookup,
            ("sensor", DOMAIN, "AA:BB:CC:DD:EE:01_node_11_src_15_transport"),
        )
        self.assertEqual(registry.updated_entity_id, "sensor.amaran_transport")
        self.assertEqual(
            registry.updated_options["disabled_by"].value,
            "integration",
        )
        self.assertEqual(
            registry.updated_options["entity_category"].value,
            "diagnostic",
        )


class FakeRegistry:
    lookup: tuple[str, str, str] | None = None
    updated_entity_id: str | None = None
    updated_options: dict[str, Any] = {}

    def async_get_entity_id(
        self, domain: str, platform: str, unique_id: str
    ) -> str:
        self.lookup = (domain, platform, unique_id)
        return "sensor.amaran_transport"

    def async_update_entity(self, entity_id: str, **kwargs: Any) -> Any:
        self.updated_entity_id = entity_id
        self.updated_options = kwargs
        return types.SimpleNamespace(disabled_by=kwargs["disabled_by"])


class FakeClient:
    address = "AA:BB:CC:DD:EE:01"
    ble_mac = address
    node_address = 0x000B
    source_address = 0x000F
    name = "Ace"
    model = "Ace 25c"
    battery_capable = True
    battery_percentage = None
    data = {
        CONF_BLE_MAC: ble_mac,
        CONF_NODE_ADDRESS: node_address,
    }


if __name__ == "__main__":
    unittest.main()
