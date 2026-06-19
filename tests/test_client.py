"""Shared mesh transport model tests."""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any
import unittest


def _make_event_module() -> types.ModuleType:
    """Build a homeassistant.helpers.event stub that records interval timers."""

    event = types.ModuleType("homeassistant.helpers.event")

    def async_track_time_interval(
        hass: Any, action: Any, interval: Any, *a: Any, **k: Any
    ) -> Any:
        record = {"action": action, "interval": interval, "cancelled": False}

        def _unsubscribe() -> None:
            record["cancelled"] = True

        record["unsubscribe"] = _unsubscribe
        hass.tracked_intervals.append(record)
        return _unsubscribe

    event.async_track_time_interval = async_track_time_interval
    return event


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
    sys.modules["homeassistant.helpers.event"] = _make_event_module()


_install_homeassistant_stubs()

import custom_components.amaran.client as client_module
from custom_components.amaran.client import (
    AmaranSidusClient,
    SidusMeshNetwork,
    get_mesh_network,
    mesh_network_key,
)
from custom_components.amaran.commands import (
    power_status_request_payloads,
    status_request_payloads,
)
from custom_components.amaran.const import (
    COLOR_MODE_COLOR_TEMP,
    CONF_ADDRESS,
    CONF_APP_KEY,
    CONF_BATTERY_CAPABLE,
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

    def test_shared_proxy_ready_uses_transport_only_availability(self) -> None:
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
        self.assertTrue(all(client.is_available for client in clients))

        for client, fixture in zip(clients, fixtures, strict=True):
            client.mark_advertisement_seen(
                types.SimpleNamespace(address=fixture[CONF_BLE_MAC], rssi=-61)
            )

        self.assertTrue(all(client.is_available for client in clients))

    def test_presence_checking_option_gates_transport_availability(
        self,
    ) -> None:
        fixtures = _fixtures()
        entry = FakeEntry(
            {CONF_FIXTURES: fixtures, CONF_SOURCE_ADDRESS: 0x000F},
            {CONF_ENABLE_PRESENCE_CHECKING: True},
        )
        mesh = SidusMeshNetwork(types.SimpleNamespace(data={}), entry, fixtures)
        mesh._transport = FakeMeshTransport(ready=True)
        clients = [
            AmaranSidusClient(
                types.SimpleNamespace(data={}), entry, fixture, mesh_network=mesh
            )
            for fixture in fixtures
        ]

        self.assertFalse(any(client.is_available for client in clients))

        for client, fixture in zip(clients, fixtures, strict=True):
            client.mark_advertisement_seen(
                types.SimpleNamespace(address=fixture[CONF_BLE_MAC], rssi=-61)
            )

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
    async def test_warmup_loop_uses_background_task_when_available(self) -> None:
        fixtures = _fixtures()
        hass = FakeTaskHass()
        entry = FakeEntry({CONF_FIXTURES: fixtures, CONF_SOURCE_ADDRESS: 0x000F})
        mesh = SidusMeshNetwork(hass, entry, fixtures)
        mesh._transport = FakeMeshTransport()

        await mesh.async_setup()
        try:
            mesh.async_start_warmup("startup")

            self.assertEqual(
                hass.background_task_names,
                ["amaran_entry-1_mesh_warmup"],
            )
            self.assertEqual(hass.setup_task_names, [])
        finally:
            await mesh.async_close()

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


class FakeTaskHass:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.background_task_names: list[str] = []
        self.setup_task_names: list[str] = []

    def async_create_background_task(
        self, coroutine: Any, name: str, **_kwargs: Any
    ) -> asyncio.Task:
        self.background_task_names.append(name)
        return asyncio.create_task(coroutine, name=name)

    def async_create_task(
        self, coroutine: Any, name: str | None = None, **_kwargs: Any
    ) -> asyncio.Task:
        if name is not None:
            self.setup_task_names.append(name)
        return asyncio.create_task(coroutine, name=name)


class FakePollMesh:
    def __init__(self, *, ready: bool = False, fail: bool = False) -> None:
        self._ready = ready
        self._fail = fail
        self.sent: list[tuple[list[bytes], int]] = []
        self.warmups: list[str] = []
        self.closed = False

    @property
    def is_ready(self) -> bool:
        return self._ready

    async def async_send_siduses(
        self,
        payloads: list[bytes],
        *,
        node_address: int,
        fixture_name: str,
        fixture_mac: str | None,
        first_payload_delay: float,
    ) -> None:
        if self._fail:
            raise RuntimeError("boom")
        self.sent.append((list(payloads), node_address))

    def async_start_warmup(self, reason: str) -> None:
        self.warmups.append(reason)

    async def async_close(self) -> None:
        self.closed = True


class FakePollHass:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.tracked_intervals: list[dict[str, Any]] = []
        self.loop = None


class PollTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Sibling test modules install and pop their own helpers.event stub via
        # sys.modules, so re-assert ours before exercising the poll scheduler.
        self._saved_event = sys.modules.get("homeassistant.helpers.event")
        sys.modules["homeassistant.helpers.event"] = _make_event_module()

    def tearDown(self) -> None:
        if self._saved_event is not None:
            sys.modules["homeassistant.helpers.event"] = self._saved_event
        else:
            sys.modules.pop("homeassistant.helpers.event", None)

    def _make_client(
        self, *, battery_capable: bool, mesh: FakePollMesh
    ) -> AmaranSidusClient:
        fixture = {
            CONF_ADDRESS: "AA:BB:CC:DD:EE:01",
            CONF_BLE_MAC: "AA:BB:CC:DD:EE:01",
            CONF_NAME: "Ace 25c",
            CONF_NET_KEY: NET_KEY,
            CONF_APP_KEY: APP_KEY,
            CONF_NODE_ADDRESS: 0x000B,
            CONF_SOURCE_ADDRESS: 0x000F,
            CONF_SUPPORTED_COLOR_MODES: [COLOR_MODE_COLOR_TEMP],
            CONF_BATTERY_CAPABLE: battery_capable,
        }
        entry = FakeEntry(dict(fixture))
        return AmaranSidusClient(FakePollHass(), entry, fixture, mesh_network=mesh)

    async def test_state_poll_sends_status_request_when_ready(self) -> None:
        mesh = FakePollMesh(ready=True)
        client = self._make_client(battery_capable=True, mesh=mesh)
        await client._async_poll_state()
        self.assertEqual(len(mesh.sent), 1)
        payloads, node = mesh.sent[0]
        self.assertEqual(node, 0x000B)
        self.assertEqual(payloads, status_request_payloads())

    async def test_battery_poll_sends_power_request_when_ready(self) -> None:
        mesh = FakePollMesh(ready=True)
        client = self._make_client(battery_capable=True, mesh=mesh)
        await client._async_poll_battery()
        self.assertEqual(len(mesh.sent), 1)
        payloads, _node = mesh.sent[0]
        self.assertEqual(payloads, power_status_request_payloads())

    async def test_poll_skips_when_transport_not_ready(self) -> None:
        mesh = FakePollMesh(ready=False)
        client = self._make_client(battery_capable=True, mesh=mesh)
        await client._async_poll_state()
        await client._async_poll_battery()
        self.assertEqual(mesh.sent, [])

    async def test_poll_failure_triggers_warmup(self) -> None:
        mesh = FakePollMesh(ready=True, fail=True)
        client = self._make_client(battery_capable=True, mesh=mesh)
        await client._async_poll_state()
        self.assertEqual(mesh.warmups, ["poll_failure"])

    async def test_status_update_is_dispatched_on_the_event_loop(self) -> None:
        fixture = _fixtures()[-1]
        hass = types.SimpleNamespace(data={}, loop=asyncio.get_running_loop())
        entry = FakeEntry({CONF_FIXTURES: [fixture], CONF_SOURCE_ADDRESS: 0x000F})
        mesh = SidusMeshNetwork(hass, entry, [fixture])
        client = AmaranSidusClient(hass, entry, fixture, mesh_network=mesh)
        received: list[dict[str, Any]] = []
        status = {"source_address": client.node_address, "power": True}

        client.subscribe_status(received.append)
        mesh._handle_status_update(status)

        self.assertEqual(received, [])
        await asyncio.sleep(0)
        self.assertEqual(received, [status])

    def test_start_polling_schedules_state_and_battery_for_battery_light(self) -> None:
        mesh = FakePollMesh(ready=True)
        client = self._make_client(battery_capable=True, mesh=mesh)
        client._start_polling()
        intervals = sorted(
            record["interval"].total_seconds()
            for record in client.hass.tracked_intervals
        )
        self.assertEqual(intervals, [30.0, 60.0])

    def test_start_polling_schedules_state_only_for_non_battery_light(self) -> None:
        mesh = FakePollMesh(ready=True)
        client = self._make_client(battery_capable=False, mesh=mesh)
        client._start_polling()
        self.assertEqual(len(client.hass.tracked_intervals), 1)
        self.assertEqual(
            client.hass.tracked_intervals[0]["interval"].total_seconds(), 30.0
        )

    async def test_disconnect_cancels_poll_timers(self) -> None:
        mesh = FakePollMesh(ready=True)
        client = self._make_client(battery_capable=True, mesh=mesh)
        client._start_polling()
        records = list(client.hass.tracked_intervals)
        await client.async_disconnect()
        self.assertTrue(records and all(record["cancelled"] for record in records))


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
