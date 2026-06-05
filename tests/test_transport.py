"""Transport behavior tests with fake BLE clients."""

from __future__ import annotations

import asyncio
import unittest

from custom_components.amaran.const import (
    PROXY_SELECTION_AUTO,
    TRANSPORT_MODE_PERSISTENT,
    TRANSPORT_MODE_TRANSIENT,
    TRANSPORT_STATE_FAILED,
    TRANSPORT_STATE_PROXY_READY,
)
from custom_components.amaran.protocol import brightness_payload_percent, power_payload
from custom_components.amaran.protocol import build_mesh_proxy_pdu, power_status_request_payload
from custom_components.amaran.transport import (
    SidusBaseTransport,
    SidusPersistentTransport,
    SidusTransientTransport,
    SidusTransportSettings,
)


NET_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
APP_KEY = bytes.fromhex("ffeeddccbbaa99887766554433221100")


class FakeSequenceManager:
    def __init__(self, sequence: int = 100000) -> None:
        self.lock = asyncio.Lock()
        self.sequence = sequence


class FakeBleDevice:
    address = "AA:BB:CC:DD:EE:FF"
    name = "Fake Sidus"
    details = "fake-details"
    source = "fake-source"


class FakeServices:
    def __init__(self) -> None:
        self.characteristic = object()

    def get_characteristic(self, uuid: str) -> object:
        return self.characteristic


class FakeBleClient:
    def __init__(self) -> None:
        self.address = "AA:BB:CC:DD:EE:FF"
        self.is_connected = True
        self.services = FakeServices()
        self.writes: list[tuple[object, bytes, bool]] = []
        self.disconnect_count = 0

    async def write_gatt_char(
        self, target: object, pdu: bytes, *, response: bool
    ) -> None:
        self.writes.append((target, pdu, response))

    async def disconnect(self) -> None:
        self.disconnect_count += 1
        self.is_connected = False


class FakeServiceInfo:
    def __init__(self, address: str, rssi: int) -> None:
        self.address = address
        self.rssi = rssi


class AutoBleDevice:
    def __init__(self, address: str) -> None:
        self.address = address
        self.name = f"Proxy {address[-2:]}"
        self.details = "auto-details"
        self.source = "auto-source"


class FakeBluetoothModule:
    def __init__(self) -> None:
        self.devices = {
            "AA:BB:CC:00:00:01": AutoBleDevice("AA:BB:CC:00:00:01"),
            "AA:BB:CC:00:00:02": AutoBleDevice("AA:BB:CC:00:00:02"),
        }
        self.service_infos = {
            "AA:BB:CC:00:00:01": FakeServiceInfo("AA:BB:CC:00:00:01", -70),
            "AA:BB:CC:00:00:02": FakeServiceInfo("AA:BB:CC:00:00:02", -42),
        }

    def async_ble_device_from_address(
        self, hass: object, address: str, *, connectable: bool
    ) -> AutoBleDevice | None:
        return self.devices.get(address)

    def async_last_service_info(
        self, hass: object, address: str, *, connectable: bool
    ) -> FakeServiceInfo | None:
        return self.service_infos.get(address)


class FakePersistentTransport(SidusPersistentTransport):
    def __init__(self, *, sequence_manager: FakeSequenceManager) -> None:
        self.save_count = 0
        self.lookup_count = 0
        self.connect_count = 0
        self.discover_count = 0
        self.clients: list[FakeBleClient] = []
        super().__init__(
            settings=_settings(),
            sequence_manager=sequence_manager,
            save_sequence=self._save_sequence,
            mode=TRANSPORT_MODE_PERSISTENT,
        )

    async def _save_sequence(self) -> None:
        self.save_count += 1

    async def _lookup_ble_device(self, *, connection_reused: bool) -> FakeBleDevice:
        self.lookup_count += 1
        self._last_bluetooth_device = {
            "address": FakeBleDevice.address,
            "name": FakeBleDevice.name,
            "details": FakeBleDevice.details,
            "source": FakeBleDevice.source,
            "connection_reused": connection_reused,
        }
        return FakeBleDevice()

    async def _connect_client(self, ble_device: FakeBleDevice) -> FakeBleClient:
        self.connect_count += 1
        client = FakeBleClient()
        self.clients.append(client)
        return client

    async def _discover_proxy_in(self, client: FakeBleClient) -> object:
        self.discover_count += 1
        return client.services.characteristic


class FailingWarmupTransport(FakePersistentTransport):
    async def _lookup_ble_device(self, *, connection_reused: bool) -> FakeBleDevice:
        self.lookup_count += 1
        raise RuntimeError("unavailable")


class FakeTransientTransport(SidusTransientTransport):
    def __init__(self, *, sequence_manager: FakeSequenceManager) -> None:
        self.save_count = 0
        self.lookup_count = 0
        self.connect_count = 0
        self.discover_count = 0
        self.clients: list[FakeBleClient] = []
        super().__init__(
            settings=_settings(),
            sequence_manager=sequence_manager,
            save_sequence=self._save_sequence,
            mode=TRANSPORT_MODE_TRANSIENT,
        )

    async def _save_sequence(self) -> None:
        self.save_count += 1

    async def _lookup_ble_device(self, *, connection_reused: bool) -> FakeBleDevice:
        self.lookup_count += 1
        self._last_bluetooth_device = {
            "address": FakeBleDevice.address,
            "name": FakeBleDevice.name,
            "details": FakeBleDevice.details,
            "source": FakeBleDevice.source,
            "connection_reused": connection_reused,
        }
        return FakeBleDevice()

    async def _connect_client(self, ble_device: FakeBleDevice) -> FakeBleClient:
        self.connect_count += 1
        client = FakeBleClient()
        self.clients.append(client)
        return client

    async def _discover_proxy_in(self, client: FakeBleClient) -> object:
        self.discover_count += 1
        return client.services.characteristic


class PersistentTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_warmup_connects_without_sequence_or_write(self) -> None:
        sequence_manager = FakeSequenceManager()
        transport = FakePersistentTransport(sequence_manager=sequence_manager)
        await transport.async_setup()

        await transport.async_warmup()

        self.assertEqual(transport.connect_count, 1)
        self.assertEqual(transport.discover_count, 1)
        self.assertEqual(len(transport.clients[0].writes), 0)
        self.assertEqual(sequence_manager.sequence, 100000)
        self.assertEqual(transport.metrics["state"], TRANSPORT_STATE_PROXY_READY)

        await transport.async_close()

    async def test_user_command_reuses_warm_connection(self) -> None:
        sequence_manager = FakeSequenceManager()
        transport = FakePersistentTransport(sequence_manager=sequence_manager)
        await transport.async_setup()

        await transport.async_warmup()
        await transport.async_send_siduses([power_payload(True)])

        self.assertEqual(transport.connect_count, 1)
        self.assertEqual(transport.discover_count, 1)
        self.assertEqual(len(transport.clients[0].writes), 1)
        self.assertEqual(
            transport.last_bluetooth_device["connection_reused"],
            True,
        )

        await transport.async_close()

    async def test_warmup_unavailable_sets_failed_state(self) -> None:
        sequence_manager = FakeSequenceManager()
        transport = FailingWarmupTransport(sequence_manager=sequence_manager)
        await transport.async_setup()

        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            await transport.async_warmup()

        self.assertEqual(transport.metrics["state"], TRANSPORT_STATE_FAILED)
        self.assertIn("unavailable", transport.metrics["last_error"])

        await transport.async_close()

    async def test_persistent_reuses_one_connection_and_cached_characteristic(
        self,
    ) -> None:
        sequence_manager = FakeSequenceManager()
        transport = FakePersistentTransport(sequence_manager=sequence_manager)
        await transport.async_setup()

        await transport.async_send_siduses([power_payload(True)])
        await transport.async_send_siduses([brightness_payload_percent(80)])

        self.assertEqual(transport.connect_count, 1)
        self.assertEqual(transport.discover_count, 1)
        self.assertEqual(len(transport.clients[0].writes), 2)
        self.assertEqual(sequence_manager.sequence, 100002)
        self.assertEqual(transport.save_count, 2)
        self.assertEqual(
            transport.last_bluetooth_device["connection_reused"],
            True,
        )
        self.assertEqual(transport.metrics["mode"], TRANSPORT_MODE_PERSISTENT)
        self.assertEqual(transport.metrics["queue_depth"], 0)

        await transport.async_close()
        self.assertEqual(transport.clients[0].disconnect_count, 1)

    async def test_persistent_shared_transport_writes_to_requested_node(self) -> None:
        sequence_manager = FakeSequenceManager()
        transport = FakePersistentTransport(sequence_manager=sequence_manager)
        await transport.async_setup()

        await transport.async_send_siduses(
            [power_payload(True)],
            node_address=0x000C,
            fixture_name="Pano 60c",
            fixture_mac="AA:BB:CC:DD:EE:02",
        )

        self.assertEqual(transport.connect_count, 1)
        self.assertEqual(transport.last_write["node_address"], 0x000C)
        self.assertEqual(transport.last_write["light_name"], "Pano 60c")
        self.assertEqual(transport.last_write["light_mac"], "AA:BB:CC:DD:EE:02")

        await transport.async_close()

    async def test_persistent_serializes_concurrent_writes(self) -> None:
        sequence_manager = FakeSequenceManager()
        transport = FakePersistentTransport(sequence_manager=sequence_manager)
        await transport.async_setup()

        await asyncio.gather(
            transport.async_send_siduses([power_payload(True)]),
            transport.async_send_siduses([brightness_payload_percent(50)]),
        )

        self.assertEqual(transport.connect_count, 1)
        self.assertEqual(len(transport.clients[0].writes), 2)
        self.assertEqual(sequence_manager.sequence, 100002)
        self.assertEqual(transport.save_count, 2)

        await transport.async_close()

    async def test_persistent_reconnects_after_cached_client_disconnects(self) -> None:
        sequence_manager = FakeSequenceManager()
        transport = FakePersistentTransport(sequence_manager=sequence_manager)
        await transport.async_setup()

        await transport.async_send_siduses([power_payload(True)])
        transport.clients[0].is_connected = False
        await transport.async_send_siduses([brightness_payload_percent(25)])

        self.assertEqual(transport.connect_count, 2)
        self.assertEqual(transport.metrics["reconnect_count"], 1)
        self.assertEqual(len(transport.clients[0].writes), 1)
        self.assertEqual(len(transport.clients[1].writes), 1)

        await transport.async_close()


class TransientTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_transient_keeps_one_shot_lifecycle(self) -> None:
        sequence_manager = FakeSequenceManager()
        transport = FakeTransientTransport(sequence_manager=sequence_manager)

        await transport.async_send_siduses([power_payload(True)])
        await transport.async_send_siduses([brightness_payload_percent(80)])

        self.assertEqual(transport.connect_count, 2)
        self.assertEqual(transport.discover_count, 2)
        self.assertEqual([client.disconnect_count for client in transport.clients], [1, 1])
        self.assertEqual(sequence_manager.sequence, 100002)
        self.assertEqual(transport.metrics["mode"], TRANSPORT_MODE_TRANSIENT)


class SequenceReservationTest(unittest.TestCase):
    def test_shared_source_sequence_across_fixtures_never_goes_backwards(self) -> None:
        sequence_manager = FakeSequenceManager(sequence=42)
        first_fixture = SidusBaseTransport(
            settings=_settings(node_address=0x0002, source_address=0x000F),
            sequence_manager=sequence_manager,
            save_sequence=_noop_save,
            mode=TRANSPORT_MODE_TRANSIENT,
        )
        second_fixture = SidusBaseTransport(
            settings=_settings(node_address=0x0004, source_address=0x000F),
            sequence_manager=sequence_manager,
            save_sequence=_noop_save,
            mode=TRANSPORT_MODE_TRANSIENT,
        )

        first_sequences = list(first_fixture._reserve_sequences(2))
        second_sequences = list(second_fixture._reserve_sequences(2))

        self.assertEqual(first_sequences, [42, 43])
        self.assertEqual(second_sequences, [44, 45])
        self.assertEqual(sequence_manager.sequence, 46)


class NotificationCaptureTest(unittest.TestCase):
    def test_decrypted_access_callback_receives_raw_sidus_payload(self) -> None:
        messages: list[dict] = []
        transport = SidusBaseTransport(
            settings=_settings(
                node_address=0x000B,
                source_address=0x000F,
                access_callback=messages.append,
            ),
            sequence_manager=FakeSequenceManager(),
            save_sequence=_noop_save,
            mode=TRANSPORT_MODE_TRANSIENT,
        )
        proxy_pdu = build_mesh_proxy_pdu(
            net_key=NET_KEY,
            app_key=APP_KEY,
            src=0x000B,
            dst=0x000F,
            seq=42,
            iv_index=0,
            sidus_payload=power_status_request_payload(),
            ttl=7,
        )

        transport._handle_proxy_out_notification(None, proxy_pdu)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["source_address"], 0x000B)
        self.assertEqual(messages[0]["destination_address"], 0x000F)
        self.assertEqual(messages[0]["opcode"], 0x26)
        self.assertEqual(messages[0]["sidus_payload"], power_status_request_payload())


class AutoProxySelectionTest(unittest.TestCase):
    def test_auto_proxy_selection_chooses_first_reachable_candidate(self) -> None:
        transport = SidusBaseTransport(
            settings=_settings(
                proxy_selection=PROXY_SELECTION_AUTO,
                proxy_candidates=("AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02"),
            ),
            sequence_manager=FakeSequenceManager(),
            save_sequence=_noop_save,
            mode=TRANSPORT_MODE_TRANSIENT,
        )

        ble_device, service_info = transport._select_auto_proxy_device(
            FakeBluetoothModule()
        )

        self.assertEqual(ble_device.address, "AA:BB:CC:00:00:01")
        self.assertEqual(service_info.rssi, -70)

    def test_unavailable_manual_proxy_falls_back_to_first_reachable(self) -> None:
        transport = SidusBaseTransport(
            settings=_settings(
                proxy_selection="manual",
                proxy_candidates=("AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02"),
            ),
            sequence_manager=FakeSequenceManager(),
            save_sequence=_noop_save,
            mode=TRANSPORT_MODE_PERSISTENT,
        )

        ble_device, service_info = transport._select_proxy_device(
            FakeBluetoothModule()
        )

        self.assertEqual(ble_device.address, "AA:BB:CC:00:00:01")
        self.assertEqual(service_info.rssi, -70)


async def _noop_save() -> None:
    return None


def _settings(
    *,
    node_address: int = 0x000B,
    source_address: int = 0x000F,
    proxy_selection: str = "manual",
    proxy_candidates: tuple[str, ...] = (),
    access_callback: object | None = None,
) -> SidusTransportSettings:
    return SidusTransportSettings(
        hass=object(),
        address="AA:BB:CC:DD:EE:FF",
        name="Fake Sidus",
        net_key=NET_KEY,
        app_key=APP_KEY,
        node_address=node_address,
        source_address=source_address,
        iv_index=0,
        ttl=7,
        proxy_selection=proxy_selection,
        proxy_address="AA:BB:CC:DD:EE:FF",
        proxy_candidates=proxy_candidates,
        access_callback=access_callback,
    )
