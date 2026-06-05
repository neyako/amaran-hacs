"""Light entity availability tests."""

from __future__ import annotations

import asyncio
from enum import Enum
import sys
import types
from typing import Any
import unittest

from custom_components.amaran.const import (
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_HS,
    CONF_BLE_MAC,
    CONF_NODE_ADDRESS,
    DOMAIN,
    TRANSPORT_STATE_DISCONNECTED,
    TRANSPORT_STATE_PROXY_READY,
    TRANSPORT_STATE_RECONNECTING,
)


def _install_homeassistant_stubs() -> type[Exception]:
    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    light = types.ModuleType("homeassistant.components.light")
    config_entries = types.ModuleType("homeassistant.config_entries")
    const = types.ModuleType("homeassistant.const")
    core = types.ModuleType("homeassistant.core")
    exceptions = types.ModuleType("homeassistant.exceptions")
    helpers = types.ModuleType("homeassistant.helpers")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    restore_state = types.ModuleType("homeassistant.helpers.restore_state")
    storage = types.ModuleType("homeassistant.helpers.storage")

    class ColorMode(str, Enum):
        BRIGHTNESS = "brightness"
        COLOR_TEMP = "color_temp"
        HS = "hs"

    class HomeAssistantError(Exception):
        pass

    class LightEntity:
        pass

    class RestoreEntity:
        pass

    light.ATTR_BRIGHTNESS = "brightness"
    light.ATTR_COLOR_TEMP_KELVIN = "color_temp_kelvin"
    light.ATTR_HS_COLOR = "hs_color"
    light.ColorMode = ColorMode
    light.LightEntity = LightEntity
    config_entries.ConfigEntry = object
    const.STATE_ON = "on"
    core.HomeAssistant = object
    exceptions.HomeAssistantError = HomeAssistantError
    device_registry.CONNECTION_BLUETOOTH = "bluetooth"
    entity_platform.AddEntitiesCallback = object
    restore_state.RestoreEntity = RestoreEntity
    storage.Store = object

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.light"] = light
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.const"] = const
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.exceptions"] = exceptions
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.device_registry"] = device_registry
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform
    sys.modules["homeassistant.helpers.restore_state"] = restore_state
    sys.modules["homeassistant.helpers.storage"] = storage
    return HomeAssistantError


HomeAssistantError = _install_homeassistant_stubs()

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
)

from custom_components.amaran.client import AmaranSidusClient
import custom_components.amaran.state_store as state_store_module
from custom_components.amaran.light import AmaranSidusLight


class FakeClient:
    address = "AA:BB:CC:DD:EE:FF"
    ble_mac = "AA:BB:CC:DD:EE:FF"
    node_address = 0x000B
    source_address = 0x000F
    name = "Fake Ace"
    model = "amaran Ace 25c"
    supported_color_modes = (COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS)
    supports_hs = True
    supports_color_temp = True
    desired_power = None
    desired_brightness = None
    desired_color_temp_kelvin = None
    desired_hs_color = None
    desired_active_color_mode = COLOR_MODE_COLOR_TEMP
    capabilities = {"supported_color_modes": list(supported_color_modes)}
    data = {
        CONF_BLE_MAC: ble_mac,
        CONF_NODE_ADDRESS: node_address,
    }

    def __init__(self) -> None:
        self.is_available = True
        self.transport_state = TRANSPORT_STATE_PROXY_READY
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.status_callback: Any = None

    def set_cached_state(self, **kwargs: Any) -> None:
        return None

    def subscribe_status(self, callback: Any) -> Any:
        self.status_callback = callback

        def _unsubscribe() -> None:
            self.status_callback = None

        return _unsubscribe

    async def async_set_hsi(self, **kwargs: Any) -> None:
        self.calls.append(("hsi", kwargs))

    async def async_set_cct(self, **kwargs: Any) -> None:
        self.calls.append(("cct", kwargs))

    async def async_set_brightness(self, **kwargs: Any) -> None:
        self.calls.append(("brightness", kwargs))

    async def async_turn_on(self) -> None:
        self.calls.append(("turn_on", {}))

    async def async_turn_off(self) -> None:
        self.calls.append(("turn_off", {}))


class LightAvailabilityTest(unittest.IsolatedAsyncioTestCase):
    def test_available_reflects_client_transport_readiness(self) -> None:
        client = FakeClient()
        light = AmaranSidusLight(client, object())

        self.assertTrue(light.available)

        client.is_available = False
        client.transport_state = TRANSPORT_STATE_DISCONNECTED

        self.assertFalse(light.available)

    async def test_turn_on_fails_immediately_when_transport_unavailable(self) -> None:
        client = FakeClient()
        client.is_available = False
        client.transport_state = TRANSPORT_STATE_DISCONNECTED
        light = AmaranSidusLight(client, object())

        with self.assertRaisesRegex(HomeAssistantError, "connection is disconnected"):
            await light.async_turn_on(**{ATTR_BRIGHTNESS: 128})

        self.assertEqual(client.calls, [])

    async def test_turn_off_fails_immediately_when_transport_unavailable(self) -> None:
        client = FakeClient()
        client.is_available = False
        client.transport_state = TRANSPORT_STATE_DISCONNECTED
        light = AmaranSidusLight(client, object())

        with self.assertRaisesRegex(HomeAssistantError, "connection is disconnected"):
            await light.async_turn_off()

        self.assertEqual(client.calls, [])


class LightStateRestoreTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeStore.next_load = None
        FakeStore.saved = []
        state_store_module.Store = FakeStore

    async def test_startup_restores_persistent_state_without_commands(self) -> None:
        client = FakeClient()
        light = _light_for_restore(
            client,
            {
                "power": True,
                "brightness": 77,
                "color_temp_kelvin": 3200,
                "hs_color": [45, 60],
                "color_mode": COLOR_MODE_COLOR_TEMP,
                "assumed_state": True,
            },
        )

        await light.async_added_to_hass()

        self.assertEqual(client.calls, [])
        self.assertTrue(light.is_on)
        self.assertEqual(light.brightness, 77)
        self.assertEqual(light.color_temp_kelvin, 3200)
        self.assertTrue(light.assumed_state)

    async def test_missing_restored_state_does_not_push_defaults_on_startup(self) -> None:
        client = FakeClient()
        light = _light_for_restore(client, None)

        await light.async_added_to_hass()

        self.assertEqual(client.calls, [])
        self.assertTrue(light.assumed_state)

    async def test_turn_on_with_restored_cct_sends_restored_values(self) -> None:
        client = FakeClient()
        light = _light_for_restore(
            client,
            {
                "power": False,
                "brightness": 64,
                "color_temp_kelvin": 3200,
                "hs_color": [0, 0],
                "color_mode": COLOR_MODE_COLOR_TEMP,
                "assumed_state": True,
            },
        )
        await light.async_added_to_hass()

        await light.async_turn_on()

        self.assertEqual(
            client.calls[-1],
            ("cct", {"brightness": 64, "kelvin": 3200, "power_on": True}),
        )
        self.assertEqual(FakeStore.saved[-1]["brightness"], 64)
        self.assertEqual(FakeStore.saved[-1]["color_temp_kelvin"], 3200)

    async def test_turn_on_with_restored_hs_sends_restored_hsi(self) -> None:
        client = FakeClient()
        light = _light_for_restore(
            client,
            {
                "power": False,
                "brightness": 200,
                "color_temp_kelvin": 5600,
                "hs_color": [120, 80],
                "color_mode": COLOR_MODE_HS,
                "assumed_state": True,
            },
        )
        await light.async_added_to_hass()

        await light.async_turn_on()

        self.assertEqual(
            client.calls[-1],
            (
                "hsi",
                {"brightness": 200, "hs_color": (120.0, 80.0), "power_on": True},
            ),
        )

    async def test_status_notification_confirms_state(self) -> None:
        client = FakeClient()
        light = _light_for_restore(
            client,
            {
                "power": False,
                "brightness": 64,
                "color_temp_kelvin": 3200,
                "hs_color": [0, 0],
                "color_mode": COLOR_MODE_COLOR_TEMP,
                "assumed_state": True,
            },
        )
        await light.async_added_to_hass()

        client.status_callback(
            {
                "power": True,
                "brightness": 180,
                "color_temp_kelvin": 4300,
                "hs_color": None,
                "color_mode": COLOR_MODE_COLOR_TEMP,
            }
        )
        await asyncio.sleep(0)

        self.assertTrue(light.is_on)
        self.assertEqual(light.brightness, 180)
        self.assertEqual(light.color_temp_kelvin, 4300)
        self.assertFalse(light.assumed_state)


class LightIconTest(unittest.TestCase):
    def test_rgb_fixture_uses_palette_icon(self) -> None:
        client = FakeClient()
        client.supports_hs = True
        client.supports_color_temp = True
        client.supported_color_modes = (COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS)

        light = AmaranSidusLight(client, object())

        self.assertEqual(light._attr_icon, "mdi:palette")

    def test_cct_fixture_uses_cct_icon(self) -> None:
        client = FakeClient()
        client.supports_hs = False
        client.supports_color_temp = True
        client.supported_color_modes = (COLOR_MODE_COLOR_TEMP,)

        light = AmaranSidusLight(client, object())

        self.assertEqual(light._attr_icon, "mdi:lightbulb-on-outline")

    def test_brightness_only_fixture_uses_fallback_icon(self) -> None:
        client = FakeClient()
        client.supports_hs = False
        client.supports_color_temp = False
        client.supported_color_modes = (COLOR_MODE_BRIGHTNESS,)

        light = AmaranSidusLight(client, object())

        self.assertEqual(light._attr_icon, "mdi:lightbulb")

    def test_device_identifier_is_fixture_mac(self) -> None:
        light = AmaranSidusLight(FakeClient(), object())

        self.assertEqual(
            light.device_info["identifiers"],
            {(DOMAIN, "AA:BB:CC:DD:EE:FF")},
        )


class ClientAvailabilityTest(unittest.TestCase):
    def test_proxy_ready_without_connection_reports_unavailable(self) -> None:
        client = object.__new__(AmaranSidusClient)
        client._mesh_network = FakeMeshNetwork(
            TRANSPORT_STATE_PROXY_READY, connected=False
        )

        self.assertEqual(client.transport_state, TRANSPORT_STATE_DISCONNECTED)
        self.assertFalse(client.is_available)

    def test_proxy_ready_with_connection_reports_available(self) -> None:
        client = object.__new__(AmaranSidusClient)
        client._mesh_network = FakeMeshNetwork(
            TRANSPORT_STATE_PROXY_READY, connected=True
        )

        self.assertEqual(client.transport_state, TRANSPORT_STATE_PROXY_READY)
        self.assertTrue(client.is_available)

    def test_idle_fixture_does_not_become_stale_after_five_minutes(self) -> None:
        client = object.__new__(AmaranSidusClient)
        client._mesh_network = FakeMeshNetwork(
            TRANSPORT_STATE_PROXY_READY, connected=True
        )
        client._last_advertisement_seen = None

        self.assertEqual(client.transport_state, TRANSPORT_STATE_PROXY_READY)
        self.assertTrue(client.is_available)
        self.assertIsNone(client.fixture_stale_seconds)

    def test_reconnecting_reports_unavailable(self) -> None:
        client = object.__new__(AmaranSidusClient)
        client._mesh_network = FakeMeshNetwork(
            TRANSPORT_STATE_RECONNECTING, connected=True
        )

        self.assertEqual(client.transport_state, TRANSPORT_STATE_RECONNECTING)
        self.assertFalse(client.is_available)


class FakeMeshNetwork:
    def __init__(self, state: str, *, connected: bool) -> None:
        self.connected = connected
        self.transport_state = (
            state
            if not (state == TRANSPORT_STATE_PROXY_READY and not connected)
            else TRANSPORT_STATE_DISCONNECTED
        )
        self.is_ready = self.transport_state == TRANSPORT_STATE_PROXY_READY


class FakeStore:
    next_load: dict[str, Any] | None = None
    saved: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def async_load(self) -> dict[str, Any] | None:
        return self.next_load

    async def async_save(self, data: dict[str, Any]) -> None:
        self.saved.append(data)


class FakeHass:
    def async_create_task(self, coroutine: Any) -> asyncio.Task:
        return asyncio.create_task(coroutine)


def _light_for_restore(
    client: FakeClient,
    stored_state: dict[str, Any] | None,
) -> AmaranSidusLight:
    FakeStore.next_load = stored_state
    light = AmaranSidusLight(client, object())
    light.hass = FakeHass()

    async def _last_state() -> Any:
        return None

    light.async_get_last_state = _last_state
    return light


if __name__ == "__main__":
    unittest.main()
