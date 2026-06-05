"""Shared mesh transport model tests."""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any
import unittest


def _install_homeassistant_stubs() -> None:
    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    storage = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.data: dict[str, Any] | None = None

        async def async_load(self) -> dict[str, Any] | None:
            return self.data

        async def async_save(self, data: dict[str, Any]) -> None:
            self.data = data

    config_entries.ConfigEntry = object
    core.HomeAssistant = object
    storage.Store = Store

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.storage"] = storage


_install_homeassistant_stubs()

import custom_components.amaran.client as client_module
from custom_components.amaran.client import (
    AmaranSidusClient,
    SidusMeshNetwork,
    get_mesh_network,
    mesh_network_key,
)
from custom_components.amaran.const import (
    COLOR_MODE_COLOR_TEMP,
    CONF_ADDRESS,
    CONF_APP_KEY,
    CONF_BLE_MAC,
    CONF_ENABLE_PRESENCE_CHECKING,
    CONF_FIXTURES,
    CONF_NAME,
    CONF_NET_KEY,
    CONF_NODE_ADDRESS,
    CONF_PROXY_ADDRESS,
    CONF_PROXY_MAC,
    CONF_SOURCE_ADDRESS,
    CONF_SUPPORTED_COLOR_MODES,
    PROXY_SELECTION_AUTO,
    PROXY_SELECTION_MANUAL,
    TRANSPORT_STATE_DISCONNECTED,
    TRANSPORT_STATE_PROXY_READY,
)

client_module.Store = sys.modules["homeassistant.helpers.storage"].Store

NET_KEY = "00112233445566778899aabbccddeeff"
APP_KEY = "ffeeddccbbaa99887766554433221100"


class FakeEntry:
    def __init__(
        self,
        data: dict[str, Any],
        options: dict[str, Any] | None = None,
        entry_id: str = "entry-1",
    ) -> None:
        self.data = data
        self.options = options or {}
        self.title = "amaran Mesh"
        self.entry_id = entry_id


class SharedMeshTransportModelTest(unittest.TestCase):
    def test_mesh_runtime_key_does_not_expose_mesh_keys(self) -> None:
        fixture = _fixtures()[0]
        entry = FakeEntry({CONF_SOURCE_ADDRESS: 0x000F})

        key = mesh_network_key(entry, fixture)

        self.assertTrue(key.startswith("mesh_"))
        self.assertNotIn(NET_KEY, key)
        self.assertNotIn(APP_KEY, key)

    def test_four_imported_fixtures_share_one_transport(self) -> None:
        fixtures = _fixtures()
        entry = FakeEntry({CONF_FIXTURES: fixtures, CONF_SOURCE_ADDRESS: 0x000F})
        hass = types.SimpleNamespace(data={})

        mesh = SidusMeshNetwork(hass, entry, fixtures)
        clients = [
            AmaranSidusClient(hass, entry, fixture, mesh_network=mesh)
            for fixture in fixtures
        ]

        self.assertEqual(len(clients), 4)
        self.assertTrue(all(client._mesh_network is mesh for client in clients))
        self.assertEqual(len({id(client._mesh_network._transport) for client in clients}), 1)
        self.assertEqual(mesh.proxy_selection, PROXY_SELECTION_AUTO)
        self.assertEqual(mesh.proxy_address, "")

    def test_manual_proxy_mac_is_preferred_for_shared_mesh(self) -> None:
        fixtures = _fixtures()
        manual_proxy = fixtures[-1][CONF_BLE_MAC]
        entry = FakeEntry(
            {CONF_FIXTURES: fixtures, CONF_SOURCE_ADDRESS: 0x000F},
            {CONF_PROXY_MAC: manual_proxy},
        )
        mesh = SidusMeshNetwork(types.SimpleNamespace(data={}), entry, fixtures)

        self.assertEqual(mesh.proxy_selection, PROXY_SELECTION_MANUAL)
        self.assertEqual(mesh.proxy_address, manual_proxy)
        self.assertEqual(mesh.proxy_candidates[0], manual_proxy)

    def test_shared_proxy_ready_requires_each_fixture_advertisement(self) -> None:
        fixtures = _fixtures()
        entry = FakeEntry({CONF_FIXTURES: fixtures, CONF_SOURCE_ADDRESS: 0x000F})
        mesh = SidusMeshNetwork(types.SimpleNamespace(data={}), entry, fixtures)
        mesh._transport = FakeMeshTransport(ready=True)
        clients = [
            AmaranSidusClient(
                types.SimpleNamespace(data={}), entry, fixture, mesh_network=mesh
            )
            for fixture in fixtures
        ]

        self.assertTrue(mesh.is_ready)
        self.assertFalse(any(client.is_available for client in clients))

        for client, fixture in zip(clients, fixtures, strict=True):
            client.mark_advertisement_seen(
                types.SimpleNamespace(address=fixture[CONF_BLE_MAC], rssi=-61)
            )

        self.assertTrue(all(client.is_available for client in clients))

    def test_presence_checking_can_be_disabled_for_transport_only_availability(
        self,
    ) -> None:
        fixtures = _fixtures()
        entry = FakeEntry(
            {CONF_FIXTURES: fixtures, CONF_SOURCE_ADDRESS: 0x000F},
            {CONF_ENABLE_PRESENCE_CHECKING: False},
        )
        mesh = SidusMeshNetwork(types.SimpleNamespace(data={}), entry, fixtures)
        mesh._transport = FakeMeshTransport(ready=True)
        clients = [
            AmaranSidusClient(
                types.SimpleNamespace(data={}), entry, fixture, mesh_network=mesh
            )
            for fixture in fixtures
        ]

        self.assertTrue(all(client.is_available for client in clients))

    def test_legacy_entries_in_same_mesh_reuse_global_runtime(self) -> None:
        fixtures = _fixtures()
        first_entry = FakeEntry(
            {**fixtures[0], CONF_SOURCE_ADDRESS: 0x000F},
            entry_id="entry-1",
        )
        second_entry = FakeEntry(
            {**fixtures[1], CONF_SOURCE_ADDRESS: 0x000F},
            entry_id="entry-2",
        )
        hass = types.SimpleNamespace(data={})

        first = get_mesh_network(
            hass,
            first_entry,
            [fixtures[0]],
            context_entries=[first_entry, second_entry],
            context_fixtures=fixtures[:2],
        )
        second = get_mesh_network(
            hass,
            second_entry,
            [fixtures[1]],
            context_entries=[first_entry, second_entry],
            context_fixtures=fixtures[:2],
        )

        self.assertIs(first, second)
        self.assertEqual(first.entry_ids, {"entry-1", "entry-2"})
        self.assertEqual(len(first.fixtures), 2)

    def test_entries_with_different_proxy_mac_use_separate_runtimes(self) -> None:
        fixtures = _fixtures()
        first_entry = FakeEntry(
            {**fixtures[0], CONF_SOURCE_ADDRESS: 0x000F},
            {CONF_PROXY_MAC: fixtures[0][CONF_BLE_MAC]},
            entry_id="entry-1",
        )
        second_entry = FakeEntry(
            {**fixtures[1], CONF_SOURCE_ADDRESS: 0x000F},
            {CONF_PROXY_MAC: fixtures[1][CONF_BLE_MAC]},
            entry_id="entry-2",
        )
        hass = types.SimpleNamespace(data={})

        first = get_mesh_network(
            hass,
            first_entry,
            [fixtures[0]],
            context_entries=[first_entry],
            context_fixtures=[fixtures[0]],
        )
        second = get_mesh_network(
            hass,
            second_entry,
            [fixtures[1]],
            context_entries=[second_entry],
            context_fixtures=[fixtures[1]],
        )

        self.assertIsNot(first, second)

    def test_blank_proxy_option_overrides_legacy_fixture_target(self) -> None:
        fixtures = _fixtures()
        first_entry = FakeEntry(
            {
                **fixtures[0],
                CONF_SOURCE_ADDRESS: 0x000F,
                CONF_PROXY_ADDRESS: fixtures[0][CONF_BLE_MAC],
            },
            {CONF_PROXY_MAC: ""},
            entry_id="entry-1",
        )
        second_entry = FakeEntry(
            {**fixtures[1], CONF_SOURCE_ADDRESS: 0x000F},
            entry_id="entry-2",
        )
        hass = types.SimpleNamespace(data={})

        first = get_mesh_network(
            hass,
            first_entry,
            [fixtures[0]],
            context_entries=[first_entry, second_entry],
            context_fixtures=fixtures[:2],
        )
        second = get_mesh_network(
            hass,
            second_entry,
            [fixtures[1]],
            context_entries=[first_entry, second_entry],
            context_fixtures=fixtures[:2],
        )

        self.assertIs(first, second)
        self.assertEqual(first.proxy_selection, PROXY_SELECTION_AUTO)


class SharedMeshReconnectTest(unittest.IsolatedAsyncioTestCase):
    async def test_reload_warmup_and_disconnect_reconnect_restore_availability(
        self,
    ) -> None:
        fixtures = _fixtures()
        hass = types.SimpleNamespace(data={})
        entry = FakeEntry(
            {CONF_FIXTURES: fixtures, CONF_SOURCE_ADDRESS: 0x000F},
            {CONF_ENABLE_PRESENCE_CHECKING: False},
        )
        mesh = SidusMeshNetwork(hass, entry, fixtures)
        transport = FakeMeshTransport()
        mesh._transport = transport
        clients = [
            AmaranSidusClient(hass, entry, fixture, mesh_network=mesh)
            for fixture in fixtures
        ]

        await mesh.async_setup()
        mesh.async_start_warmup("reload")
        await _wait_for(lambda: transport.warmup_count == 1)

        self.assertTrue(all(client.is_available for client in clients))

        transport.connected = False
        transport.state = TRANSPORT_STATE_DISCONNECTED
        mesh.async_start_warmup("disconnect")
        await _wait_for(lambda: transport.warmup_count == 2)

        self.assertTrue(all(client.is_available for client in clients))
        await mesh.async_close()


class FakeMeshTransport:
    def __init__(self, *, ready: bool = False) -> None:
        self.connected = ready
        self.state = (
            TRANSPORT_STATE_PROXY_READY if ready else TRANSPORT_STATE_DISCONNECTED
        )
        self.warmup_count = 0
        self.last_bluetooth_device = None
        self.last_write = None

    @property
    def metrics(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "selected_proxy_address": "AA:BB:CC:DD:EE:01",
        }

    async def async_setup(self) -> None:
        return None

    async def async_warmup(self) -> None:
        self.warmup_count += 1
        self.connected = True
        self.state = TRANSPORT_STATE_PROXY_READY

    async def async_close(self) -> None:
        self.connected = False
        self.state = TRANSPORT_STATE_DISCONNECTED


async def _wait_for(predicate: Any) -> None:
    for _ in range(20):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not reached")


def _fixtures() -> list[dict[str, Any]]:
    return [
        _fixture("100x S", "70:3E:97:F6:8F:27", 0x0002),
        _fixture("Pano 60c", "AA:BB:CC:DD:EE:02", 0x0004),
        _fixture("60x S", "AA:BB:CC:DD:EE:03", 0x000A),
        _fixture("Ace 25c", "AA:BB:CC:DD:EE:01", 0x000B),
    ]


def _fixture(name: str, mac: str, node_address: int) -> dict[str, Any]:
    return {
        CONF_ADDRESS: mac,
        CONF_BLE_MAC: mac,
        CONF_NAME: name,
        CONF_NET_KEY: NET_KEY,
        CONF_APP_KEY: APP_KEY,
        CONF_NODE_ADDRESS: node_address,
        CONF_SUPPORTED_COLOR_MODES: [COLOR_MODE_COLOR_TEMP],
    }


if __name__ == "__main__":
    unittest.main()
