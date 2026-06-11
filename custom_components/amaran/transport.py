"""BLE transport layers for Amaran Sidus mesh proxy writes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
import time
from typing import Any

from .const import (
    MESH_PROXY_IN_UUID,
    MESH_PROXY_OUT_UUID,
    PROXY_SELECTION_AUTO,
    TRANSPORT_STATE_DISCONNECTED,
    TRANSPORT_STATE_FAILED,
    TRANSPORT_STATE_PROXY_READY,
    TRANSPORT_STATE_RECONNECTING,
    TRANSPORT_STATE_WARMING,
)
from .protocol import access_payload, build_mesh_proxy_pdu, decode_mesh_proxy_access

_LOGGER = logging.getLogger(__name__)

_INTER_PAYLOAD_DELAY = 0.05
_CONNECT_TIMEOUT = 10.0


@dataclass(frozen=True)
class SidusTransportSettings:
    """Immutable settings shared by transient and persistent transports."""

    hass: Any
    address: str
    name: str
    net_key: bytes
    app_key: bytes
    node_address: int
    source_address: int
    iv_index: int
    ttl: int
    proxy_selection: str = PROXY_SELECTION_AUTO
    proxy_address: str = ""
    proxy_candidates: tuple[str, ...] = ()
    status_callback: Callable[[dict[str, Any]], None] | None = None
    access_callback: Callable[[dict[str, Any]], None] | None = None


@dataclass
class SidusTransportMetrics:
    """Last-known transport timings and counters."""

    mode: str
    state: str = TRANSPORT_STATE_DISCONNECTED
    connected: bool = False
    queue_depth: int = 0
    reconnect_count: int = 0
    connect_ms: float = 0.0
    bluetooth_lookup_ms: float = 0.0
    service_discovery_ms: float = 0.0
    characteristic_resolve_ms: float = 0.0
    write_ms: float = 0.0
    disconnect_ms: float = 0.0
    proxy_in_found: bool = False
    selected_proxy_address: str | None = None
    selected_proxy_rssi: int | None = None
    last_connect_time: float | None = None
    last_write_time: float | None = None
    last_notification_time: float | None = None
    notification_count: int = 0
    notify_enabled: bool = False
    last_decoded_status: dict[str, Any] | None = None
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return diagnostics-friendly metrics."""

        return {
            "mode": self.mode,
            "state": self.state,
            "connected": self.connected,
            "queue_depth": self.queue_depth,
            "reconnect_count": self.reconnect_count,
            "bluetooth_lookup_ms": round(self.bluetooth_lookup_ms, 1),
            "connect_ms": round(self.connect_ms, 1),
            "service_discovery_ms": round(self.service_discovery_ms, 1),
            "characteristic_resolve_ms": round(self.characteristic_resolve_ms, 1),
            "write_ms": round(self.write_ms, 1),
            "last_write_latency_ms": round(self.write_ms, 1),
            "disconnect_ms": round(self.disconnect_ms, 1),
            "proxy_in_found": self.proxy_in_found,
            "selected_proxy_address": self.selected_proxy_address,
            "selected_proxy_rssi": self.selected_proxy_rssi,
            "last_connect_time": self.last_connect_time,
            "last_write_time": self.last_write_time,
            "last_notification_time": self.last_notification_time,
            "notification_count": self.notification_count,
            "notify_enabled": self.notify_enabled,
            "last_decoded_status": self.last_decoded_status,
            "last_error": self.last_error,
        }


@dataclass
class _WriteRequest:
    sidus_payloads: list[bytes]
    first_payload_delay: float
    future: asyncio.Future[None]
    node_address: int
    fixture_name: str
    fixture_mac: str | None
    warmup: bool = False


class SidusBaseTransport:
    """Shared mesh PDU and sequence handling for transport implementations."""

    def __init__(
        self,
        *,
        settings: SidusTransportSettings,
        sequence_manager: Any,
        save_sequence: Callable[[], Awaitable[None]],
        mode: str,
    ) -> None:
        self._settings = settings
        self._sequence_manager = sequence_manager
        self._save_sequence = save_sequence
        self._metrics = SidusTransportMetrics(mode=mode)
        self._last_bluetooth_device: dict[str, Any] | None = None
        self._last_write: dict[str, Any] | None = None
        self._failed_proxy_addresses: set[str] = set()
        self._proxy_out_target: Any | None = None

    @property
    def connected(self) -> bool:
        """Return current transport connection state."""

        return False

    @property
    def last_bluetooth_device(self) -> dict[str, Any] | None:
        """Return last BLE path selected by the transport."""

        return self._last_bluetooth_device

    @property
    def last_write(self) -> dict[str, Any] | None:
        """Return last write metadata."""

        return self._last_write

    @property
    def metrics(self) -> dict[str, Any]:
        """Return transport metrics."""

        self._metrics.connected = self.connected
        return self._metrics.as_dict()

    async def async_setup(self) -> None:
        """Prepare transport resources."""

    async def async_close(self) -> None:
        """Release transport resources."""

    async def async_send_siduses(
        self,
        sidus_payloads: list[bytes],
        *,
        node_address: int | None = None,
        fixture_name: str | None = None,
        fixture_mac: str | None = None,
        first_payload_delay: float = 0.0,
    ) -> None:
        """Write Sidus payloads."""

        raise NotImplementedError

    async def async_warmup(self) -> None:
        """Resolve/connect/discover the Mesh Proxy Data In characteristic."""

        raise NotImplementedError

    def _set_state(self, state: str, error: str | None = None) -> None:
        self._metrics.state = state
        self._metrics.last_error = error

    def _reserve_sequences(
        self, count: int, *, node_address: int | None = None
    ) -> range:
        destination = self._settings.node_address if node_address is None else node_address
        start_sequence = self._sequence_manager.sequence
        last_sequence = start_sequence + count - 1
        if start_sequence > 0xFFFFFF or last_sequence > 0xFFFFFF:
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError(
                "Bluetooth Mesh sequence exhausted; IV update is not implemented"
            )

        self._sequence_manager.sequence = last_sequence + 1
        _LOGGER.debug(
            "Reserved Sidus sequence block first=%s next=%s count=%s "
            "node=0x%04x src=0x%04x",
            start_sequence,
            self._sequence_manager.sequence,
            count,
            destination,
            self._settings.source_address,
        )
        return range(start_sequence, start_sequence + count)

    async def _lookup_ble_device(self, *, connection_reused: bool) -> Any:
        from homeassistant.components import bluetooth
        from homeassistant.exceptions import HomeAssistantError

        lookup_start = time.perf_counter()
        _LOGGER.debug(
            "Sidus timing bluetooth_lookup_start connection_selection=%s "
            "connection_address=%s candidates=%s",
            self._settings.proxy_selection,
            self._settings.proxy_address or self._settings.address,
            self._settings.proxy_candidates,
        )
        ble_device, service_info = self._select_proxy_device(bluetooth)
        self._metrics.bluetooth_lookup_ms = _elapsed_ms(lookup_start)
        _LOGGER.debug(
            "Sidus timing bluetooth_lookup_ms=%.1f proxy_selection=%s found=%s",
            self._metrics.bluetooth_lookup_ms,
            self._settings.proxy_selection,
            ble_device is not None,
        )
        if ble_device is None:
            raise HomeAssistantError("No connectable Amaran BLE path found")

        rssi = _service_info_rssi(service_info)
        self._metrics.selected_proxy_address = ble_device.address
        self._metrics.selected_proxy_rssi = rssi
        self._last_bluetooth_device = {
            "address": ble_device.address,
            "name": ble_device.name,
            "details": repr(getattr(ble_device, "details", None)),
            "source": repr(getattr(ble_device, "source", None)),
            "rssi": rssi,
            "proxy_selection": self._settings.proxy_selection,
            "configured_proxy_address": self._settings.proxy_address or None,
            "connection_reused": connection_reused,
        }
        _LOGGER.debug(
            "Selected Sidus BLE path connection_selection=%s selected_ble_mac=%s "
            "name=%s rssi=%s source=%s details=%s reused=%s",
            self._settings.proxy_selection,
            ble_device.address,
            ble_device.name,
            rssi,
            self._last_bluetooth_device["source"],
            self._last_bluetooth_device["details"],
            connection_reused,
        )
        return ble_device

    def _manual_proxy_address(self) -> str:
        return (self._settings.proxy_address or self._settings.address).strip()

    def _select_proxy_device(self, bluetooth: Any) -> tuple[Any | None, Any | None]:
        """Prefer manual proxy, then fall back across reachable candidates."""

        excluded = set(self._failed_proxy_addresses)
        for _attempt in range(2):
            if self._settings.proxy_selection != PROXY_SELECTION_AUTO:
                target_address = self._manual_proxy_address()
                if target_address.lower() not in excluded:
                    service_info = _last_service_info_for_address(
                        bluetooth, self._settings.hass, target_address
                    )
                    ble_device = bluetooth.async_ble_device_from_address(
                        self._settings.hass, target_address, connectable=True
                    )
                    if ble_device is not None:
                        return ble_device, service_info
                _LOGGER.debug(
                    "Preferred Sidus BLE path unavailable; falling back "
                    "preferred_ble_mac=%s",
                    target_address,
                )

            ble_device, service_info = self._select_auto_proxy_device(
                bluetooth, excluded=excluded
            )
            if ble_device is not None:
                return ble_device, service_info
            if not excluded:
                break
            excluded.clear()
            self._failed_proxy_addresses.clear()
        return None, None

    def _select_auto_proxy_device(
        self, bluetooth: Any, *, excluded: set[str] | None = None
    ) -> tuple[Any | None, Any | None]:
        candidates = _dedupe_addresses(
            [
                *self._settings.proxy_candidates,
                self._settings.proxy_address,
                self._settings.address,
            ]
        )
        excluded = excluded or set()
        reachable: list[tuple[int | None, str, Any, Any | None]] = []
        for address in candidates:
            if address.lower() in excluded:
                continue
            ble_device = bluetooth.async_ble_device_from_address(
                self._settings.hass, address, connectable=True
            )
            if ble_device is None:
                continue
            service_info = _last_service_info_for_address(
                bluetooth, self._settings.hass, address
            )
            reachable.append(
                (
                    _service_info_rssi(service_info),
                    str(getattr(ble_device, "address", address)),
                    ble_device,
                    service_info,
                )
            )

        if not reachable:
            return None, None

        rssi, address, ble_device, service_info = reachable[0]
        _LOGGER.debug(
            "Sidus auto BLE candidates=%s selected_ble_mac=%s selected_rssi=%s",
            [
                {"address": item[1], "rssi": item[0]}
                for item in reachable
            ],
            address,
            rssi,
        )
        return ble_device, service_info

    async def _connect_client(self, ble_device: Any) -> Any:
        from bleak import BleakClient
        from bleak_retry_connector import establish_connection

        connect_start = time.perf_counter()
        _LOGGER.debug(
            "Sidus timing connect_start resolved_address=%s name=%s",
            ble_device.address,
            ble_device.name,
        )
        try:
            client = await establish_connection(
                BleakClient,
                ble_device,
                self._settings.name,
                timeout=_CONNECT_TIMEOUT,
            )
        except Exception:
            self._failed_proxy_addresses.add(str(ble_device.address).lower())
            raise
        self._failed_proxy_addresses.clear()
        self._metrics.connect_ms = _elapsed_ms(connect_start)
        self._metrics.last_connect_time = time.time()
        _LOGGER.debug(
            "Sidus timing connect_end_ms=%.1f resolved_address=%s",
            self._metrics.connect_ms,
            ble_device.address,
        )
        return client

    async def _discover_proxy_in(self, client: Any) -> Any:
        service_start = time.perf_counter()
        _LOGGER.debug(
            "Sidus timing service_discovery_start address=%s",
            self._last_bluetooth_device["address"] if self._last_bluetooth_device else None,
        )
        services = await _async_get_services(client)
        self._metrics.service_discovery_ms = _elapsed_ms(service_start)
        _LOGGER.debug(
            "Sidus timing service_discovery_ms=%.1f services_found=%s",
            self._metrics.service_discovery_ms,
            services is not None,
        )

        char_start = time.perf_counter()
        _LOGGER.debug(
            "Sidus timing characteristic_resolve_start uuid=%s",
            MESH_PROXY_IN_UUID,
        )
        proxy_in = _resolve_proxy_in_char(client, services)
        self._metrics.proxy_in_found = proxy_in is not None
        self._metrics.characteristic_resolve_ms = _elapsed_ms(char_start)
        _LOGGER.debug(
            "Sidus timing characteristic_resolve_ms=%.1f proxy_in_found=%s",
            self._metrics.characteristic_resolve_ms,
            self._metrics.proxy_in_found,
        )
        proxy_out = _resolve_gatt_char(client, services, MESH_PROXY_OUT_UUID)
        await self._start_proxy_out_notify(client, proxy_out)
        return proxy_in or MESH_PROXY_IN_UUID

    async def _start_proxy_out_notify(self, client: Any, proxy_out: Any | None) -> None:
        self._metrics.notify_enabled = False
        self._proxy_out_target = proxy_out
        start_notify = getattr(client, "start_notify", None)
        if proxy_out is None or not callable(start_notify):
            return
        try:
            await start_notify(proxy_out, self._handle_proxy_out_notification)
        except Exception as err:  # pragma: no cover - backend-specific notify support
            _LOGGER.debug("Sidus Mesh Proxy Data Out notify unavailable: %s", err)
            return
        self._metrics.notify_enabled = True
        _LOGGER.debug("Sidus Mesh Proxy Data Out notifications enabled")

    def _handle_proxy_out_notification(self, _sender: Any, data: Any) -> None:
        raw = bytes(data)
        self._metrics.notification_count += 1
        self._metrics.last_notification_time = time.time()
        decoded = decode_mesh_proxy_access(
            net_key=self._settings.net_key,
            app_key=self._settings.app_key,
            iv_index=self._settings.iv_index,
            proxy_pdu=raw,
        )
        if decoded is None:
            _LOGGER.debug(
                "Sidus Mesh Proxy Data Out notification len=%s type=0x%02x raw=%s",
                len(raw),
                raw[0] & 0x3F if raw else -1,
                raw.hex(" "),
            )
            return
        self._notify_access_callback(decoded)
        status = decoded.sidus_status
        if status is None:
            _LOGGER.debug(
                "Sidus decoded access src=0x%04x dst=0x%04x seq=%s access=%s",
                decoded.source_address,
                decoded.destination_address,
                decoded.sequence,
                decoded.access_payload.hex(" "),
            )
            return
        payload = {
            "power": status.power,
            "brightness": status.brightness,
            "color_temp_kelvin": status.color_temp_kelvin,
            "hs_color": status.hs_color,
            "color_mode": status.color_mode,
            "source_address": status.source_address,
            "destination_address": status.destination_address,
            "sequence": status.sequence,
            "received_at": time.time(),
        }
        self._metrics.last_decoded_status = payload
        _LOGGER.debug(
            "Sidus status notification light_node=0x%04x dst=0x%04x "
            "power=%s brightness=%s cct=%s hs=%s mode=%s",
            status.source_address,
            status.destination_address,
            status.power,
            status.brightness,
            status.color_temp_kelvin,
            status.hs_color,
            status.color_mode,
        )
        if self._settings.status_callback is not None:
            self._settings.status_callback(payload)

    def _notify_access_callback(self, decoded: Any) -> None:
        callback = self._settings.access_callback
        if callback is None:
            return
        access = decoded.access_payload
        sidus_payload = decoded.sidus_payload
        payload = {
            "source_address": decoded.source_address,
            "destination_address": decoded.destination_address,
            "sequence": decoded.sequence,
            "opcode": access[0] if access else None,
            "access_payload": access,
            "sidus_payload": sidus_payload,
            "sidus_power_info": decoded.sidus_power_info,
            "received_at": time.time(),
        }
        callback(payload)

    async def _write_reserved(
        self,
        *,
        client: Any,
        write_target: Any,
        sequences: range,
        sidus_payloads: list[bytes],
        node_address: int,
        fixture_name: str,
        fixture_mac: str | None,
        first_payload_delay: float,
    ) -> None:
        for index, (current_sequence, sidus_payload) in enumerate(
            zip(sequences, sidus_payloads)
        ):
            access = access_payload(sidus_payload)
            _LOGGER.debug(
                "Sidus payload write light=%s light_mac=%s light_node=0x%04x "
                "selected_ble_mac=%s dst=0x%04x seq=%s src=0x%04x "
                "sidus=%s access=%s",
                fixture_name,
                fixture_mac,
                node_address,
                self._last_bluetooth_device["address"]
                if self._last_bluetooth_device
                else None,
                node_address,
                current_sequence,
                self._settings.source_address,
                sidus_payload.hex(" "),
                access.hex(" "),
            )
            proxy_pdu = build_mesh_proxy_pdu(
                net_key=self._settings.net_key,
                app_key=self._settings.app_key,
                src=self._settings.source_address,
                dst=node_address,
                seq=current_sequence,
                iv_index=self._settings.iv_index,
                sidus_payload=sidus_payload,
                ttl=self._settings.ttl,
            )
            _LOGGER.debug(
                "Writing Sidus proxy PDU seq=%s src=0x%04x dst=0x%04x "
                "iv_index=%s ttl=%s resolved_address=%s len=%s header=%s",
                current_sequence,
                self._settings.source_address,
                node_address,
                self._settings.iv_index,
                self._settings.ttl,
                self._last_bluetooth_device["address"]
                if self._last_bluetooth_device
                else None,
                len(proxy_pdu),
                proxy_pdu[:2].hex(),
            )
            write_start = time.perf_counter()
            _LOGGER.debug(
                "Sidus timing write_start seq=%s len=%s queue_depth=%s mode=%s",
                current_sequence,
                len(proxy_pdu),
                self._metrics.queue_depth,
                self._metrics.mode,
            )
            await client.write_gatt_char(write_target, proxy_pdu, response=False)
            self._metrics.write_ms = _elapsed_ms(write_start)
            self._metrics.last_write_time = time.time()
            self._metrics.last_error = None
            _LOGGER.debug(
                "Sidus timing write_end_ms=%.1f seq=%s",
                self._metrics.write_ms,
                current_sequence,
            )
            self._last_write = {
                "sequence": current_sequence,
                "next_sequence": current_sequence + 1,
                "source_address": self._settings.source_address,
                "node_address": node_address,
                "light_name": fixture_name,
                "light_mac": fixture_mac,
                "iv_index": self._settings.iv_index,
                "ttl": self._settings.ttl,
                "pdu_len": len(proxy_pdu),
                "pdu_header": proxy_pdu[:2].hex(),
                "resolved_address": self._last_bluetooth_device["address"]
                if self._last_bluetooth_device
                else None,
                **self.metrics,
            }
            if index < len(sidus_payloads) - 1:
                delay = (
                    first_payload_delay
                    if index == 0 and first_payload_delay
                    else _INTER_PAYLOAD_DELAY
                )
                await asyncio.sleep(delay)


class SidusTransientTransport(SidusBaseTransport):
    """Connect, write, disconnect for each command."""

    async def async_warmup(self) -> None:
        """Warm the transient path, then close the one-shot connection."""

        client = None
        self._metrics.queue_depth = 0
        self._metrics.disconnect_ms = 0.0
        self._set_state(TRANSPORT_STATE_WARMING)
        try:
            ble_device = await self._lookup_ble_device(connection_reused=False)
            client = await self._connect_client(ble_device)
            await self._discover_proxy_in(client)
            self._set_state(TRANSPORT_STATE_PROXY_READY)
        except Exception as err:
            self._set_state(TRANSPORT_STATE_FAILED, repr(err))
            raise
        finally:
            if client is not None:
                disconnect_start = time.perf_counter()
                try:
                    await client.disconnect()
                finally:
                    self._metrics.disconnect_ms = _elapsed_ms(disconnect_start)
                    self._set_state(TRANSPORT_STATE_DISCONNECTED)

    async def async_send_siduses(
        self,
        sidus_payloads: list[bytes],
        *,
        node_address: int | None = None,
        fixture_name: str | None = None,
        fixture_mac: str | None = None,
        first_payload_delay: float = 0.0,
    ) -> None:
        """Write Sidus payloads with the original one-shot BLE lifecycle."""

        if not sidus_payloads:
            return

        destination = self._settings.node_address if node_address is None else node_address
        async with self._sequence_manager.lock:
            sequences = self._reserve_sequences(
                len(sidus_payloads), node_address=destination
            )
            await self._save_sequence()

            client = None
            self._metrics.queue_depth = 0
            self._metrics.disconnect_ms = 0.0
            try:
                self._set_state(TRANSPORT_STATE_RECONNECTING)
                ble_device = await self._lookup_ble_device(connection_reused=False)
                client = await self._connect_client(ble_device)
                write_target = await self._discover_proxy_in(client)
                self._set_state(TRANSPORT_STATE_PROXY_READY)
                await self._write_reserved(
                    client=client,
                    write_target=write_target,
                    sequences=sequences,
                    sidus_payloads=sidus_payloads,
                    node_address=destination,
                    fixture_name=fixture_name or self._settings.name,
                    fixture_mac=fixture_mac,
                    first_payload_delay=first_payload_delay,
                )
            except Exception as err:
                self._set_state(TRANSPORT_STATE_FAILED, repr(err))
                raise
            finally:
                if client is not None:
                    disconnect_start = time.perf_counter()
                    _LOGGER.debug(
                        "Sidus timing disconnect_start resolved_address=%s",
                        getattr(client, "address", None),
                    )
                    try:
                        await client.disconnect()
                    finally:
                        self._metrics.disconnect_ms = _elapsed_ms(disconnect_start)
                        _LOGGER.debug(
                            "Sidus timing disconnect_end_ms=%.1f",
                            self._metrics.disconnect_ms,
                        )
                        if self._last_write is not None:
                            self._last_write["disconnect_ms"] = round(
                                self._metrics.disconnect_ms, 1
                            )
                        if self._metrics.state != TRANSPORT_STATE_FAILED:
                            self._set_state(TRANSPORT_STATE_DISCONNECTED)


class SidusPersistentTransport(SidusBaseTransport):
    """Long-lived BLE session with serialized queued writes."""

    def __init__(
        self,
        *,
        settings: SidusTransportSettings,
        sequence_manager: Any,
        save_sequence: Callable[[], Awaitable[None]],
        mode: str,
    ) -> None:
        super().__init__(
            settings=settings,
            sequence_manager=sequence_manager,
            save_sequence=save_sequence,
            mode=mode,
        )
        self._queue: asyncio.Queue[_WriteRequest | None] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._client: Any | None = None
        self._write_target: Any | None = None
        self._has_connected = False

    @property
    def connected(self) -> bool:
        """Return true when the cached Bleak client is connected."""

        if self._client is None:
            return False
        try:
            return bool(getattr(self._client, "is_connected", False))
        except Exception:
            return False

    async def async_setup(self) -> None:
        """Start the persistent worker."""

        if self._worker_task is None or self._worker_task.done():
            name = f"amaran_{self._settings.address}_ble_worker"
            coroutine = self._worker_loop()
            create_background_task = getattr(
                self._settings.hass, "async_create_background_task", None
            )
            if callable(create_background_task):
                self._worker_task = create_background_task(coroutine, name=name)
            else:
                create_task = getattr(self._settings.hass, "async_create_task", None)
                if callable(create_task):
                    self._worker_task = create_task(coroutine, name=name)
                else:
                    self._worker_task = asyncio.create_task(coroutine, name=name)

    async def async_close(self) -> None:
        """Stop worker and close the cached BLE session."""

        if self._worker_task is not None:
            await self._queue.put(None)
            await self._worker_task
            self._worker_task = None
        await self._disconnect_cached()

    async def async_send_siduses(
        self,
        sidus_payloads: list[bytes],
        *,
        node_address: int | None = None,
        fixture_name: str | None = None,
        fixture_mac: str | None = None,
        first_payload_delay: float = 0.0,
    ) -> None:
        """Queue Sidus payloads and wait for worker completion."""

        if not sidus_payloads:
            return
        if self._worker_task is None or self._worker_task.done():
            await self.async_setup()

        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        await self._queue.put(
            _WriteRequest(
                sidus_payloads=list(sidus_payloads),
                first_payload_delay=first_payload_delay,
                future=future,
                node_address=self._settings.node_address
                if node_address is None
                else node_address,
                fixture_name=fixture_name or self._settings.name,
                fixture_mac=fixture_mac,
                warmup=False,
            )
        )
        self._metrics.queue_depth = self._queue.qsize()
        await future

    async def async_warmup(self) -> None:
        """Queue connection/discovery without sending a Sidus command."""

        if self._worker_task is None or self._worker_task.done():
            await self.async_setup()

        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        await self._queue.put(
            _WriteRequest(
                sidus_payloads=[],
                first_payload_delay=0.0,
                future=future,
                node_address=self._settings.node_address,
                fixture_name=self._settings.name,
                fixture_mac=None,
                warmup=True,
            )
        )
        self._metrics.queue_depth = self._queue.qsize()
        await future

    async def _worker_loop(self) -> None:
        while True:
            request = await self._queue.get()
            self._metrics.queue_depth = self._queue.qsize()
            if request is None:
                self._queue.task_done()
                return

            try:
                await self._process_request(request)
            except Exception as err:
                self._set_state(TRANSPORT_STATE_FAILED, repr(err))
                await self._disconnect_cached()
                if not request.future.done():
                    request.future.set_exception(err)
            else:
                if not request.future.done():
                    request.future.set_result(None)
            finally:
                self._metrics.queue_depth = self._queue.qsize()
                self._queue.task_done()

    async def _process_request(self, request: _WriteRequest) -> None:
        if request.warmup:
            self._set_state(
                TRANSPORT_STATE_RECONNECTING
                if self._has_connected
                else TRANSPORT_STATE_WARMING
            )
            await self._ensure_connected()
            self._set_state(TRANSPORT_STATE_PROXY_READY)
            return

        async with self._sequence_manager.lock:
            sequences = self._reserve_sequences(
                len(request.sidus_payloads), node_address=request.node_address
            )
            await self._save_sequence()
            client = await self._ensure_connected()
            self._set_state(TRANSPORT_STATE_PROXY_READY)
            await self._write_reserved(
                client=client,
                write_target=self._write_target or MESH_PROXY_IN_UUID,
                sequences=sequences,
                sidus_payloads=request.sidus_payloads,
                node_address=request.node_address,
                fixture_name=request.fixture_name,
                fixture_mac=request.fixture_mac,
                first_payload_delay=request.first_payload_delay,
            )

    async def _ensure_connected(self) -> Any:
        if self.connected:
            if self._last_bluetooth_device is not None:
                self._last_bluetooth_device["connection_reused"] = True
            self._set_state(TRANSPORT_STATE_PROXY_READY)
            return self._client

        if self._client is not None or self._has_connected:
            self._metrics.reconnect_count += 1
            self._set_state(TRANSPORT_STATE_RECONNECTING)
        else:
            self._set_state(TRANSPORT_STATE_WARMING)
        await self._disconnect_cached()
        ble_device = await self._lookup_ble_device(connection_reused=False)
        self._client = await self._connect_client(ble_device)
        self._write_target = await self._discover_proxy_in(self._client)
        self._has_connected = True
        self._metrics.disconnect_ms = 0.0
        self._set_state(TRANSPORT_STATE_PROXY_READY)
        return self._client

    async def _disconnect_cached(self) -> None:
        client = self._client
        self._client = None
        self._write_target = None
        if client is None:
            if self._metrics.state != TRANSPORT_STATE_FAILED:
                self._set_state(TRANSPORT_STATE_DISCONNECTED)
            return

        disconnect_start = time.perf_counter()
        try:
            await client.disconnect()
        except Exception as err:  # pragma: no cover - backend-specific cleanup
            _LOGGER.debug("Sidus persistent disconnect failed: %s", err)
        finally:
            self._metrics.disconnect_ms = _elapsed_ms(disconnect_start)
            if self._metrics.state != TRANSPORT_STATE_FAILED:
                self._set_state(TRANSPORT_STATE_DISCONNECTED)


async def _async_get_services(client: Any) -> Any | None:
    try:
        services = getattr(client, "services", None)
    except Exception as err:  # pragma: no cover - depends on Bleak backend
        _LOGGER.debug("Sidus service collection unavailable: %s", err)
        services = None
    if services is not None:
        return services

    get_services = getattr(client, "get_services", None)
    if callable(get_services):
        try:
            return await get_services()
        except Exception as err:  # pragma: no cover - depends on Bleak backend
            _LOGGER.debug("Sidus explicit service discovery failed: %s", err)
    return None


def _resolve_proxy_in_char(client: Any, services: Any | None) -> Any | None:
    return _resolve_gatt_char(client, services, MESH_PROXY_IN_UUID)


def _resolve_gatt_char(client: Any, services: Any | None, uuid: str) -> Any | None:
    if services is None:
        try:
            services = getattr(client, "services", None)
        except Exception as err:  # pragma: no cover - depends on Bleak backend
            _LOGGER.debug("Sidus service collection unavailable: %s", err)
            return None

    get_characteristic = getattr(services, "get_characteristic", None)
    if callable(get_characteristic):
        return get_characteristic(uuid)
    return None


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _dedupe_addresses(addresses: list[str]) -> tuple[str, ...]:
    return tuple(
        value
        for value in dict.fromkeys(str(address).strip() for address in addresses)
        if value
    )


def _last_service_info_for_address(
    bluetooth: Any, hass: Any, address: str
) -> Any | None:
    last_service_info = getattr(bluetooth, "async_last_service_info", None)
    if callable(last_service_info):
        return last_service_info(hass, address, connectable=True)

    discovered = getattr(bluetooth, "async_discovered_service_info", None)
    if not callable(discovered):
        return None
    for service_info in discovered(hass, connectable=True) or []:
        if str(getattr(service_info, "address", "")).lower() == address.lower():
            return service_info
    return None


def _service_info_rssi(service_info: Any | None) -> int | None:
    if service_info is None:
        return None
    rssi = getattr(service_info, "rssi", None)
    return int(rssi) if rssi is not None else None
