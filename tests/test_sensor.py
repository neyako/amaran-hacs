"""Transport diagnostic sensor UX tests."""

from __future__ import annotations

from enum import Enum
import sys
import types
from typing import Any
import unittest
from unittest import mock


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
    core.callback = lambda fn: fn
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

    binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")
    binary_sensor.BinarySensorEntity = SensorEntity
    binary_sensor.BinarySensorDeviceClass = types.SimpleNamespace(PLUG="plug")
    sys.modules["homeassistant.components.binary_sensor"] = binary_sensor
    select = types.ModuleType("homeassistant.components.select")
    select.SelectEntity = SensorEntity
    sys.modules["homeassistant.components.select"] = select
    light = sys.modules.setdefault(
        "homeassistant.components.light", types.ModuleType("homeassistant.components.light")
    )
    light.ATTR_EFFECT = "effect"
    light.EFFECT_OFF = "off"
    const.STATE_OFF = "off"
    const.STATE_UNKNOWN = "unknown"
    const.STATE_UNAVAILABLE = "unavailable"
    exceptions = sys.modules.setdefault(
        "homeassistant.exceptions", types.ModuleType("homeassistant.exceptions")
    )
    if not hasattr(exceptions, "HomeAssistantError"):
        exceptions.HomeAssistantError = RuntimeError
    event = sys.modules.setdefault(
        "homeassistant.helpers.event", types.ModuleType("homeassistant.helpers.event")
    )
    event.async_track_state_change_event = mock.Mock(return_value=lambda: None)
    storage = sys.modules.setdefault(
        "homeassistant.helpers.storage", types.ModuleType("homeassistant.helpers.storage")
    )
    if not hasattr(storage, "Store"):
        storage.Store = object


_install_sensor_stubs()

from custom_components.amaran.const import CONF_BLE_MAC, CONF_NODE_ADDRESS, DOMAIN
import custom_components.amaran.sensor as sensor_module
import custom_components.amaran.binary_sensor as power_module
import custom_components.amaran.select as select_module
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

    async def test_external_power_requires_real_report_and_battery_profile(self) -> None:
        client = FakeClient()
        client.is_available = True
        client.battery_power_info = None
        sensor = power_module.AmaranExternalPowerSensor(client)
        self.assertIsNone(sensor.is_on)
        self.assertFalse(sensor.available)
        client.battery_power_info = {"external_voltage": 15000}
        self.assertTrue(sensor.is_on)
        self.assertTrue(sensor.available)
        client.battery_power_info = {"external_voltage": 0}
        self.assertFalse(sensor.is_on)
        self.assertTrue(sensor.available)
        client.is_available = False
        self.assertFalse(sensor.available)
        mains_client = FakeClient()
        mains_client.battery_capable = False
        added = []
        await power_module.async_setup_entry(
            types.SimpleNamespace(data={DOMAIN: {"entry": [client, mains_client]}}),
            types.SimpleNamespace(entry_id="entry"), added.extend,
        )
        self.assertEqual(len(added), 1)

    async def test_effect_chooser_mirrors_light_and_reuses_service_without_waking_off(self) -> None:
        client = FakeClient()
        client.supported_effects = ("Fire", "TV")
        entity = select_module.AmaranEffectSelect(client)
        light = types.SimpleNamespace(state="off", attributes={"effect": "Fire"})
        service = mock.AsyncMock()
        entity.hass = types.SimpleNamespace(
            states=types.SimpleNamespace(get=lambda entity_id: light),
            services=types.SimpleNamespace(async_call=service),
        )
        entity._context = object()
        entity.async_on_remove = mock.Mock()
        registry = types.SimpleNamespace(
            async_get_entity_id=mock.Mock(return_value="light.renamed_ace")
        )
        with mock.patch.object(select_module.er, "async_get", return_value=registry):
            await entity.async_added_to_hass()
        self.assertEqual(entity._light_entity_id, "light.renamed_ace")
        service.assert_not_awaited()
        self.assertEqual(entity.current_option, "off")
        await entity.async_select_option("off")
        service.assert_not_awaited()
        await entity.async_select_option("Fire")
        service.assert_awaited_once_with(
            "light", "turn_on", {"entity_id": "light.renamed_ace", "effect": "Fire"},
            blocking=True, context=entity._context,
        )
        light.state = "on"
        self.assertEqual(entity.current_option, "Fire")
        light.attributes = {}
        self.assertEqual(entity.current_option, "off")
        with self.assertRaises(select_module.HomeAssistantError):
            await entity.async_select_option("Unsupported")
        light.state = "unavailable"
        self.assertFalse(entity.available)
        self.assertIsNone(entity.current_option)
        with self.assertRaises(select_module.HomeAssistantError):
            await entity.async_select_option("Fire")


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
