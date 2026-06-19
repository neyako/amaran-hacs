"""Bluetooth client for Amaran Sidus mesh proxy control."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
import hashlib
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_HS,
    CONF_ADDRESS,
    CONF_APP_KEY,
    CONF_BATTERY_CAPABLE,
    CONF_BATTERY_PERCENTAGE,
    CONF_BLE_MAC,
    CONF_DEVICE_UUID,
    CONF_ENABLE_PRESENCE_CHECKING,
    CONF_IV_INDEX,
    CONF_MODEL,
    CONF_NAME,
    CONF_NET_KEY,
    CONF_NODE_ADDRESS,
    CONF_PROXY_ADDRESS,
    CONF_PROXY_CANDIDATES,
    CONF_PROXY_MAC,
    CONF_SEQUENCE,
    CONF_SOURCE_ADDRESS,
    CONF_SUPPORTED_COLOR_MODES,
    CONF_TTL,
    DEFAULT_BATTERY_POLL_INTERVAL_SECONDS,
    DEFAULT_IV_INDEX,
    DEFAULT_ENABLE_PRESENCE_CHECKING,
    DEFAULT_NAME,
    DEFAULT_NODE_ADDRESS,
    DEFAULT_PRESENCE_UNAVAILABLE_AFTER_SECONDS,
    DEFAULT_SEQUENCE,
    DEFAULT_SOURCE_ADDRESS,
    DEFAULT_STATE_POLL_INTERVAL_SECONDS,
    DEFAULT_TTL,
    DOMAIN,
    MAX_COLOR_TEMP_KELVIN,
    MIN_COLOR_TEMP_KELVIN,
    PROXY_SELECTION_AUTO,
    PROXY_SELECTION_MANUAL,
    TRANSPORT_MODE_PERSISTENT,
    TRANSPORT_STATE_CONNECTED,
    TRANSPORT_STATE_DISCONNECTED,
    TRANSPORT_STATE_PROXY_READY,
)
from .commands import (
    brightness_cct_payload,
    brightness_payloads,
    cct_payloads,
    hsi_payloads,
    power_status_request_payloads,
    power_off_payloads,
    power_on_payloads,
    status_request_payloads,
)
from .fixtures import detect_fixture_profile, supported_color_modes_for_fixture
from .protocol import (
    access_payload,
    normalize_hex_key,
)
from .transport import (
    SidusPersistentTransport,
    SidusTransportSettings,
)
from .warmup import WarmupRetryPolicy

_LOGGER = logging.getLogger(__name__)

_STORE_VERSION = 1
_SEQUENCE_MANAGERS = f"{DOMAIN}_sequence_managers"
_MESH_NETWORKS = f"{DOMAIN}_mesh_networks"
_POWER_SETTLE_DELAY = 0.05
_MESH_MONITOR_INTERVAL = 5.0
_AVAILABLE_TRANSPORT_STATES = {
    TRANSPORT_STATE_CONNECTED,
    TRANSPORT_STATE_PROXY_READY,
}


class SidusSequenceManager:
    """Shared sequence state for one mesh key/source/IV tuple."""

    def __init__(self, hass: HomeAssistant, storage_key: str) -> None:
        self._store: Store[dict[str, int]] = Store(
            hass, _STORE_VERSION, f"{DOMAIN}_{storage_key}"
        )
        self.lock = asyncio.Lock()
        self.sequence = DEFAULT_SEQUENCE
        self._loaded = False

    async def async_setup(
        self,
        *,
        initial_sequence: int,
        node_address: int,
        source_address: int,
        iv_index: int,
    ) -> None:
        """Load persisted sequence once and merge it with entry data."""

        if self._loaded:
            self.sequence = max(self.sequence, initial_sequence)
            return

        self.sequence = initial_sequence
        data = await self._store.async_load()
        if data and CONF_SEQUENCE in data:
            self.sequence = max(self.sequence, int(data[CONF_SEQUENCE]))
        self._loaded = True
        _LOGGER.debug(
            "Loaded Sidus sequence seq=%s node=0x%04x src=0x%04x iv_index=%s",
            self.sequence,
            node_address,
            source_address,
            iv_index,
        )

    async def async_save(
        self, *, node_address: int, source_address: int, iv_index: int
    ) -> None:
        """Persist the next sequence reserved for this mesh source."""

        await self._store.async_save(
            {
                CONF_SEQUENCE: self.sequence,
                CONF_NODE_ADDRESS: node_address,
                CONF_SOURCE_ADDRESS: source_address,
                CONF_IV_INDEX: iv_index,
            }
        )


class SidusMeshNetwork:
    """Own one BLE Mesh Proxy transport for one imported mesh."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        fixtures: list[dict[str, Any]],
        entries: list[ConfigEntry] | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.fixtures = list(fixtures)
        self.entries = list(entries or [entry])
        self._entry_ids: set[str] = set()
        fixture = self.fixtures[0] if self.fixtures else entry.data
        data = {**entry.data, **fixture}

        self._net_key = normalize_hex_key(data[CONF_NET_KEY], field="network key")
        self._app_key = normalize_hex_key(data[CONF_APP_KEY], field="app key")
        self._source_address = int(
            data.get(CONF_SOURCE_ADDRESS, DEFAULT_SOURCE_ADDRESS)
        )
        self._iv_index = int(data.get(CONF_IV_INDEX, DEFAULT_IV_INDEX))
        self._ttl = int(data.get(CONF_TTL, DEFAULT_TTL))
        self._initial_sequence = int(data.get(CONF_SEQUENCE, DEFAULT_SEQUENCE))
        self._node_address = int(data.get(CONF_NODE_ADDRESS, DEFAULT_NODE_ADDRESS))
        self._proxy_mac = _configured_proxy_mac(self.entries, data)
        self._proxy_selection = (
            PROXY_SELECTION_MANUAL if self._proxy_mac else PROXY_SELECTION_AUTO
        )
        self._proxy_candidates = _mesh_proxy_candidates(
            self.fixtures,
            _configured_proxy_candidates(self.entries),
            self._proxy_mac,
        )
        if not self._proxy_candidates:
            self._proxy_candidates = (str(data[CONF_ADDRESS]),)
        proxy_address = self._proxy_mac or self._proxy_candidates[0]

        sequence_managers: dict[str, SidusSequenceManager] = hass.data.setdefault(
            _SEQUENCE_MANAGERS, {}
        )
        sequence_key = _sequence_storage_key(
            self._net_key, self._source_address, self._iv_index
        )
        self._sequence_manager = sequence_managers.setdefault(
            sequence_key, SidusSequenceManager(hass, sequence_key)
        )
        self._status_callbacks: dict[int, list[Any]] = {}
        self._access_callbacks: list[Any] = []
        settings = SidusTransportSettings(
            hass=hass,
            address=proxy_address,
            name=entry.title or "amaran",
            net_key=self._net_key,
            app_key=self._app_key,
            node_address=self._node_address,
            source_address=self._source_address,
            iv_index=self._iv_index,
            ttl=self._ttl,
            proxy_selection=self._proxy_selection,
            proxy_address=self._proxy_mac,
            proxy_candidates=self._proxy_candidates,
            status_callback=self._handle_status_update,
            access_callback=self._handle_access_update,
            disconnect_callback=self._handle_ble_disconnect,
        )
        self._transport = SidusPersistentTransport(
            settings=settings,
            sequence_manager=self._sequence_manager,
            save_sequence=self._async_save_sequence,
            mode=TRANSPORT_MODE_PERSISTENT,
        )
        self._last_proxy_advertisement_seen: float | None = None
        self._warmup_task: asyncio.Task[None] | None = None
        self._warmup_event = asyncio.Event()
        self._warmup_policy = WarmupRetryPolicy()
        self._setup_lock = asyncio.Lock()
        self._setup_complete = False
        self._closing = False

    @property
    def sequence(self) -> int:
        """Return next shared mesh sequence number."""

        return self._sequence_manager.sequence

    @property
    def source_address(self) -> int:
        """Return shared mesh source address."""

        return self._source_address

    @property
    def proxy_address(self) -> str:
        """Return configured manual proxy MAC, or empty for auto."""

        return self._proxy_mac

    @property
    def proxy_selection(self) -> str:
        """Return manual or automatic shared proxy selection."""

        return self._proxy_selection

    @property
    def proxy_candidates(self) -> tuple[str, ...]:
        """Return known fixture/proxy addresses for discovery callbacks."""

        return self._proxy_candidates

    @property
    def entry_ids(self) -> set[str]:
        """Return config entries currently using this mesh runtime."""

        return set(self._entry_ids)

    def attach_entry(
        self, entry: ConfigEntry, fixtures: list[dict[str, Any]]
    ) -> None:
        """Attach a config entry and merge its fixture destinations."""

        self._entry_ids.add(entry.entry_id)
        known = {_fixture_identity(fixture) for fixture in self.fixtures}
        for fixture in fixtures:
            if _fixture_identity(fixture) not in known:
                self.fixtures.append(fixture)
                known.add(_fixture_identity(fixture))

    def detach_entry(self, entry_id: str) -> bool:
        """Detach an entry and return true when no users remain."""

        self._entry_ids.discard(entry_id)
        return not self._entry_ids

    @property
    def last_proxy_advertisement_seen(self) -> float | None:
        """Return last known advertisement from a proxy candidate."""

        return self._last_proxy_advertisement_seen

    @property
    def last_bluetooth_device(self) -> dict[str, Any] | None:
        """Return selected shared BLE proxy details."""

        return self._transport.last_bluetooth_device

    @property
    def last_write(self) -> dict[str, Any] | None:
        """Return last shared proxy write details."""

        return self._transport.last_write

    @property
    def transport_metrics(self) -> dict[str, Any]:
        """Return shared transport metrics."""

        return self._transport.metrics

    @property
    def transport_state(self) -> str:
        """Return shared transport state without fixture advertisement gating."""

        state = str(self.transport_metrics.get("state", TRANSPORT_STATE_DISCONNECTED))
        if state in _AVAILABLE_TRANSPORT_STATES and not self.connected:
            return TRANSPORT_STATE_DISCONNECTED
        return state

    @property
    def is_ready(self) -> bool:
        """Return true when shared proxy is connected and 2ADD is cached."""

        return self.transport_state in _AVAILABLE_TRANSPORT_STATES

    @property
    def connected(self) -> bool:
        """Return true when shared proxy connection is alive."""

        return self._transport.connected

    def mark_proxy_advertisement_seen(self, service_info: Any) -> None:
        """Record proxy candidate advertisement and wake reconnect loop."""

        address = str(getattr(service_info, "address", "") or "").strip()
        if not address or not _address_matches(address, self._proxy_candidates):
            return
        self._last_proxy_advertisement_seen = time.time()
        if not self.is_ready:
            self.async_start_warmup("proxy_advertisement")

    def subscribe_status(self, node_address: int, callback: Any) -> Any:
        """Subscribe to decoded light status notifications for one node."""

        callbacks = self._status_callbacks.setdefault(int(node_address), [])
        callbacks.append(callback)

        def _unsubscribe() -> None:
            if callback in callbacks:
                callbacks.remove(callback)

        return _unsubscribe

    def subscribe_access(self, callback: Any) -> Any:
        """Subscribe to decrypted access messages on this mesh."""

        self._access_callbacks.append(callback)

        def _unsubscribe() -> None:
            if callback in self._access_callbacks:
                self._access_callbacks.remove(callback)

        return _unsubscribe

    def _handle_status_update(self, status: dict[str, Any]) -> None:
        source_address = int(status.get("source_address", 0))
        loop = getattr(getattr(self, "hass", None), "loop", None)
        for callback in tuple(self._status_callbacks.get(source_address, ())):
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(callback, status)
            else:
                callback(status)

    def _handle_access_update(self, message: dict[str, Any]) -> None:
        for callback in tuple(self._access_callbacks):
            callback(message)

    def _handle_ble_disconnect(self) -> None:
        """Reconnect the shared proxy after an unexpected BLE link drop."""

        self.async_start_warmup("ble_disconnect")

    async def async_setup(self) -> None:
        """Load sequence state and start shared transport worker once."""

        async with self._setup_lock:
            if self._setup_complete:
                return
            await self._sequence_manager.async_setup(
                initial_sequence=self._initial_sequence,
                node_address=self._node_address,
                source_address=self._source_address,
                iv_index=self._iv_index,
            )
            await self._transport.async_setup()
            self._setup_complete = True

    def async_start_warmup(self, reason: str) -> None:
        """Start or wake shared connect/reconnect monitor."""

        if self._closing:
            return
        self._warmup_policy.reset()
        self._warmup_event.set()
        if self._warmup_task is not None and not self._warmup_task.done():
            return

        name = f"amaran_{self.entry.entry_id}_mesh_warmup"
        coroutine = self._async_warmup_loop(reason)
        create_background_task = getattr(
            self.hass, "async_create_background_task", None
        )
        if callable(create_background_task):
            self._warmup_task = create_background_task(coroutine, name=name)
        else:
            create_task = getattr(self.hass, "async_create_task", None)
            if callable(create_task):
                self._warmup_task = create_task(coroutine, name=name)
            else:
                self._warmup_task = asyncio.create_task(coroutine, name=name)

    async def _async_warmup_loop(self, reason: str) -> None:
        backoff = self._warmup_policy
        while not self._closing:
            self._warmup_event.clear()
            if not self.is_ready:
                try:
                    await self._transport.async_warmup()
                except Exception as err:  # pragma: no cover - backend-specific
                    delay = backoff.next_delay()
                    _LOGGER.warning(
                        "Sidus connection warm-up failed lights=%s delay=%.1fs error=%r",
                        len(self.fixtures),
                        delay,
                        err,
                    )
                    with suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(self._warmup_event.wait(), timeout=delay)
                    reason = "retry"
                    continue

                backoff.reset()
                _LOGGER.info(
                    "Using BLE connection %s for %s Amaran lights",
                    self.transport_metrics.get("selected_proxy_address"),
                    len(self.fixtures),
                )

            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    self._warmup_event.wait(), timeout=_MESH_MONITOR_INTERVAL
                )
            if not self.is_ready:
                _LOGGER.warning(
                    "Sidus BLE connection disconnected; reconnecting lights=%s reason=%s",
                    len(self.fixtures),
                    reason,
                )
                reason = "disconnect"

    async def async_send_siduses(
        self,
        sidus_payloads: list[bytes],
        *,
        node_address: int,
        fixture_name: str,
        fixture_mac: str | None,
        first_payload_delay: float,
    ) -> None:
        """Send fixture command through shared proxy transport."""

        try:
            await self._transport.async_send_siduses(
                sidus_payloads,
                node_address=node_address,
                fixture_name=fixture_name,
                fixture_mac=fixture_mac,
                first_payload_delay=first_payload_delay,
            )
        except Exception:
            self.async_start_warmup("command_failure")
            raise

    async def async_close(self) -> None:
        """Stop shared reconnect monitor and proxy worker."""

        if self._closing:
            return
        self._closing = True
        self._warmup_event.set()
        if self._warmup_task is not None:
            self._warmup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._warmup_task
            self._warmup_task = None
        await self._transport.async_close()

    async def _async_save_sequence(self) -> None:
        await self._sequence_manager.async_save(
            node_address=self._node_address,
            source_address=self._source_address,
            iv_index=self._iv_index,
        )


class AmaranSidusClient:
    """Send Sidus commands through a Home Assistant Bluetooth connection."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        fixture_data: dict[str, Any] | None = None,
        mesh_network: SidusMeshNetwork | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.data = {**entry.data, **(fixture_data or {})}
        self.address: str = self.data[CONF_ADDRESS]
        self.ble_mac: str | None = self.data.get(CONF_BLE_MAC)
        self.device_uuid: str | None = self.data.get(CONF_DEVICE_UUID)
        self.name: str = self.data.get(CONF_NAME) or entry.title or DEFAULT_NAME
        self.model: str = self.data.get(CONF_MODEL) or detect_fixture_profile(
            name=self.name
        ).model
        self._supported_color_modes = supported_color_modes_for_fixture(self.data)
        self._node_address = int(self.data.get(CONF_NODE_ADDRESS, DEFAULT_NODE_ADDRESS))
        self._mesh_network = mesh_network or SidusMeshNetwork(
            hass,
            entry,
            [fixture_data or self.data],
        )
        self._last_advertisement_seen: float | None = None
        self._last_advertisement_address: str | None = None
        self._last_advertisement_rssi: int | None = None
        self._presence_checking_enabled = _entry_bool(
            entry,
            CONF_ENABLE_PRESENCE_CHECKING,
            DEFAULT_ENABLE_PRESENCE_CHECKING,
        )
        self._presence_unavailable_after = DEFAULT_PRESENCE_UNAVAILABLE_AFTER_SECONDS
        self._availability_callbacks: list[Any] = []
        self._presence_expire_unsubscribe: Any | None = None
        self._last_command: dict[str, Any] | None = None
        self._last_physical_validation: dict[str, Any] | None = None
        self._desired_power: bool | None = None
        self._desired_brightness: int | None = None
        self._desired_color_temp_kelvin: int | None = None
        self._desired_hs_color: tuple[float, float] | None = None
        self._desired_active_color_mode: str = COLOR_MODE_COLOR_TEMP
        self._battery_percentage: int | None = _optional_percentage(
            self.data.get(CONF_BATTERY_PERCENTAGE)
        )
        self._battery_power_info: dict[str, Any] | None = None
        self._battery_callbacks: list[Any] = []
        self._battery_unsubscribe: Any | None = None
        self._state_poll_unsub: Any | None = None
        self._battery_poll_unsub: Any | None = None

    @property
    def node_address(self) -> int:
        """Return the mesh destination address."""

        return self._node_address

    @property
    def sequence(self) -> int:
        """Return next mesh sequence number."""

        return self._mesh_network.sequence

    @property
    def source_address(self) -> int:
        """Return the mesh source address."""

        return self._mesh_network.source_address

    @property
    def proxy_address(self) -> str:
        """Return configured manual proxy address, if any."""

        return self._mesh_network.proxy_address

    @property
    def proxy_selection(self) -> str:
        """Return configured proxy selection mode."""

        return self._mesh_network.proxy_selection

    @property
    def last_advertisement_seen(self) -> float | None:
        """Return last fixture advertisement timestamp."""

        return self._last_advertisement_seen

    @property
    def last_advertisement_address(self) -> str | None:
        """Return last fixture advertisement address."""

        return self._last_advertisement_address

    @property
    def last_advertisement_rssi(self) -> int | None:
        """Return last fixture advertisement RSSI."""

        return self._last_advertisement_rssi

    @property
    def last_proxy_advertisement_seen(self) -> float | None:
        """Return last selected proxy advertisement timestamp."""

        return self._mesh_network.last_proxy_advertisement_seen

    @property
    def presence_checking_enabled(self) -> bool:
        """Return true when light advertisements gate availability."""

        return self._presence_checking_enabled

    @property
    def presence_unavailable_after(self) -> float:
        """Return seconds before a light advertisement is reported stale."""

        return self._presence_unavailable_after

    @property
    def fixture_reachable(self) -> bool:
        """Return true when the shared mesh transport can send commands."""

        return self.is_available

    @property
    def fixture_stale_seconds(self) -> float | None:
        """Return seconds past the advertisement freshness window."""

        if not self._presence_checking_enabled or self._last_advertisement_seen is None:
            return None
        stale_seconds = (
            time.time()
            - self._last_advertisement_seen
            - self._presence_unavailable_after
        )
        if stale_seconds <= 0:
            return None
        return round(stale_seconds, 1)

    @property
    def last_command(self) -> dict[str, Any] | None:
        """Return last command diagnostics."""

        return self._last_command

    @property
    def last_physical_validation(self) -> dict[str, Any] | None:
        """Return last physical validation diagnostics."""

        return self._last_physical_validation

    @property
    def supported_color_modes(self) -> tuple[str, ...]:
        """Return configured HA color modes for this fixture."""

        return self._supported_color_modes

    @property
    def capabilities(self) -> dict[str, Any]:
        """Return capability details for diagnostics/logging."""

        return {
            "supported_color_modes": list(self._supported_color_modes),
            "source_supported_color_modes": self.data.get(CONF_SUPPORTED_COLOR_MODES),
            "battery_capable": self.battery_capable,
            "name": self.name,
            "model": self.model,
        }

    @property
    def battery_capable(self) -> bool:
        """Return true for known battery-powered lights."""

        return bool(self.data.get(CONF_BATTERY_CAPABLE))

    @property
    def battery_percentage(self) -> int | None:
        """Return last known battery percentage, if a real value exists."""

        return self._battery_percentage

    @property
    def battery_power_info(self) -> dict[str, Any] | None:
        """Return last decoded real power/battery packet details."""

        return self._battery_power_info

    @property
    def supports_hs(self) -> bool:
        """Return true when this fixture supports HSI commands."""

        return COLOR_MODE_HS in self._supported_color_modes

    @property
    def supports_color_temp(self) -> bool:
        """Return true when this fixture supports CCT commands."""

        return COLOR_MODE_COLOR_TEMP in self._supported_color_modes

    @property
    def last_bluetooth_device(self) -> dict[str, Any] | None:
        """Return the last selected Bluetooth path."""

        return self._mesh_network.last_bluetooth_device

    @property
    def last_write(self) -> dict[str, Any] | None:
        """Return details for the last proxy write."""

        return self._mesh_network.last_write

    @property
    def transport_mode(self) -> str:
        """Return configured transport mode."""

        return TRANSPORT_MODE_PERSISTENT

    @property
    def transport_metrics(self) -> dict[str, Any]:
        """Return BLE transport metrics."""

        return self._mesh_network.transport_metrics

    @property
    def transport_state(self) -> str:
        """Return the transport warm-up/connection state."""

        return self._mesh_network.transport_state

    @property
    def is_available(self) -> bool:
        """Return true when the shared transport and enabled light gate are ready."""

        return self._mesh_network.is_ready and self._fixture_presence_ok()

    @property
    def last_connect_time(self) -> float | None:
        """Return the last successful connect time as a UNIX timestamp."""

        value = self.transport_metrics.get("last_connect_time")
        return float(value) if value is not None else None

    @property
    def last_write_latency_ms(self) -> float:
        """Return the last proxy write latency."""

        return float(self.transport_metrics.get("last_write_latency_ms", 0.0))

    @property
    def desired_brightness(self) -> int | None:
        """Return cached target HA brightness."""

        return self._desired_brightness

    @property
    def desired_power(self) -> bool | None:
        """Return cached target power state."""

        return self._desired_power

    @property
    def desired_color_temp_kelvin(self) -> int | None:
        """Return cached target color temperature."""

        return self._desired_color_temp_kelvin

    @property
    def desired_hs_color(self) -> tuple[float, float] | None:
        """Return cached target HS color."""

        return self._desired_hs_color

    @property
    def desired_active_color_mode(self) -> str:
        """Return cached active color mode."""

        return self._desired_active_color_mode

    @property
    def connected(self) -> bool:
        """Return current transport connection state."""

        return self._mesh_network.connected

    def subscribe_status(self, callback: Any) -> Any:
        """Subscribe to decoded status updates for this light."""

        return self._mesh_network.subscribe_status(self._node_address, callback)

    def subscribe_access(self, callback: Any) -> Any:
        """Subscribe to decrypted access updates for this mesh."""

        return self._mesh_network.subscribe_access(callback)

    def subscribe_availability(self, callback: Any) -> Any:
        """Subscribe to light-level availability changes."""

        self._availability_callbacks.append(callback)

        def _unsubscribe() -> None:
            if callback in self._availability_callbacks:
                self._availability_callbacks.remove(callback)

        return _unsubscribe

    def subscribe_battery(self, callback: Any) -> Any:
        """Subscribe to decoded battery updates for this light."""

        self._battery_callbacks.append(callback)

        def _unsubscribe() -> None:
            if callback in self._battery_callbacks:
                self._battery_callbacks.remove(callback)

        return _unsubscribe

    def mark_advertisement_seen(self, service_info: Any) -> None:
        """Record fixture advertisement freshness."""

        address = str(getattr(service_info, "address", "") or "").strip()
        if not address:
            return
        was_available = self.is_available
        seen_at = _advertisement_seen_at(service_info)
        if _address_matches(address, self._fixture_advertisement_addresses()):
            self._last_advertisement_seen = seen_at
            self._last_advertisement_address = address
            rssi = getattr(service_info, "rssi", None)
            self._last_advertisement_rssi = int(rssi) if rssi is not None else None
            self._schedule_presence_expiry()
            if self.is_available != was_available:
                self._notify_availability_callbacks()

    def _fixture_advertisement_addresses(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in dict.fromkeys((self.ble_mac or "", self.address))
            if value
        )

    def _seed_last_advertisement_from_cache(self) -> None:
        try:
            from homeassistant.components import bluetooth
        except Exception:
            return

        last_service_info = getattr(bluetooth, "async_last_service_info", None)
        if not callable(last_service_info):
            return
        for address in self._fixture_advertisement_addresses():
            service_info = last_service_info(self.hass, address, connectable=False)
            if service_info is not None:
                self.mark_advertisement_seen(service_info)
                return

    async def async_setup(self) -> None:
        """Load persisted sequence state."""

        self._seed_last_advertisement_from_cache()
        await self._mesh_network.async_setup()
        if self.battery_capable and self._battery_unsubscribe is None:
            self._battery_unsubscribe = self.subscribe_access(
                self._handle_power_info_update
            )
        self._start_polling()

    def _start_polling(self) -> None:
        """Schedule periodic state (and battery) polls to keep HA in sync.

        The light only reports its state when asked, so without polling a
        physical knob change never reaches HA and the battery stays unknown.
        Each poll is a harmless status request that never changes the light, and
        is skipped while the shared transport is not ready (e.g. at startup).
        """

        from homeassistant.helpers.event import async_track_time_interval

        if self._state_poll_unsub is None:
            self._state_poll_unsub = async_track_time_interval(
                self.hass,
                self._async_poll_state,
                timedelta(seconds=DEFAULT_STATE_POLL_INTERVAL_SECONDS),
            )
        if self.battery_capable and self._battery_poll_unsub is None:
            self._battery_poll_unsub = async_track_time_interval(
                self.hass,
                self._async_poll_battery,
                timedelta(seconds=DEFAULT_BATTERY_POLL_INTERVAL_SECONDS),
            )

    async def _async_poll_state(self, _now: Any = None) -> None:
        """Pull the light's current state so manual (knob) changes sync to HA."""

        await self._async_send_poll(status_request_payloads(), kind="state")

    async def _async_poll_battery(self, _now: Any = None) -> None:
        """Pull the light's battery/power report for the battery sensor."""

        await self._async_send_poll(power_status_request_payloads(), kind="battery")

    async def _async_send_poll(self, payloads: list[bytes], *, kind: str) -> None:
        """Send a status request without touching user-facing command diagnostics."""

        if not self._mesh_network.is_ready:
            return
        try:
            await self._mesh_network.async_send_siduses(
                payloads,
                node_address=self._node_address,
                fixture_name=self.name,
                fixture_mac=self.ble_mac,
                first_payload_delay=0.0,
            )
        except Exception as err:
            _LOGGER.debug(
                "Sidus %s poll failed light=%s error=%r", kind, self.name, err
            )
            self.async_start_warmup("poll_failure")

    def async_start_warmup(self, reason: str) -> None:
        """Start or wake background warm-up without blocking HA startup."""

        self._mesh_network.async_start_warmup(reason)

    def set_cached_state(
        self,
        *,
        power: bool | None = None,
        brightness: int | None = None,
        kelvin: int | None = None,
        hs_color: tuple[float, float] | None = None,
        active_color_mode: str | None = None,
    ) -> None:
        """Seed the optimistic target state from Home Assistant restore data."""

        if power is not None:
            self._desired_power = bool(power)
        if brightness is not None:
            self._desired_brightness = _clamp_brightness(brightness)
        if kelvin is not None:
            self._desired_color_temp_kelvin = _clamp_kelvin(kelvin)
        if hs_color is not None:
            self._desired_hs_color = _clamp_hs(hs_color)
        if active_color_mode in (
            COLOR_MODE_BRIGHTNESS,
            COLOR_MODE_COLOR_TEMP,
            COLOR_MODE_HS,
        ):
            self._desired_active_color_mode = active_color_mode

    async def async_disconnect(self) -> None:
        """Close transport resources."""

        self._cancel_presence_expiry()
        if self._battery_unsubscribe is not None:
            self._battery_unsubscribe()
            self._battery_unsubscribe = None
        if self._state_poll_unsub is not None:
            self._state_poll_unsub()
            self._state_poll_unsub = None
        if self._battery_poll_unsub is not None:
            self._battery_poll_unsub()
            self._battery_poll_unsub = None
        await self._mesh_network.async_close()

    async def async_request_power_status(self, *, capture_seconds: float = 10.0) -> None:
        """Send the debug Sidus power/battery status request and log responses."""

        capture_seconds = max(0.0, min(60.0, float(capture_seconds)))
        payloads = power_status_request_payloads()
        requested_at = _utc_timestamp(time.time())
        _LOGGER.warning(
            "Sidus power status probe tx ts=%s light=%s light_node=0x%04x "
            "src=0x%04x dst=0x%04x opcode=0x%02x raw_payload=%s "
            "capture_seconds=%.1f",
            requested_at,
            self.name,
            self._node_address,
            self.source_address,
            self._node_address,
            payloads[-1][9],
            payloads[-1].hex(" "),
            capture_seconds,
        )

        def _log_access(message: dict[str, Any]) -> None:
            source_address = int(message.get("source_address", 0))
            destination_address = int(message.get("destination_address", 0))
            opcode = message.get("opcode")
            access_payload = message.get("access_payload") or b""
            sidus_payload = message.get("sidus_payload") or b""
            sidus_command = sidus_payload[9] if len(sidus_payload) >= 10 else None
            power_info = message.get("sidus_power_info")
            _LOGGER.warning(
                "Sidus power status probe rx ts=%s light=%s light_node=0x%04x "
                "src=0x%04x dst=0x%04x seq=%s opcode=%s sidus_command=%s "
                "raw_access=%s raw_payload=%s decoded_mode=%s "
                "decoded_battery=%s decoded_time=%s",
                _utc_timestamp(float(message.get("received_at", time.time()))),
                self.name,
                self._node_address,
                source_address,
                destination_address,
                message.get("sequence"),
                _hex_byte(opcode),
                _hex_byte(sidus_command),
                bytes(access_payload).hex(" "),
                bytes(sidus_payload).hex(" "),
                getattr(power_info, "power_supply_mode", None),
                getattr(power_info, "battery_percentage", None),
                getattr(power_info, "battery_time_minutes", None),
            )

        unsubscribe = self.subscribe_access(_log_access)
        try:
            await self.async_send_siduses(payloads)
            if capture_seconds:
                await asyncio.sleep(capture_seconds)
        finally:
            unsubscribe()

    async def async_turn_on(self, extra_payloads: list[bytes] | None = None) -> None:
        """Send the Sidus power-on payload, followed by optional payloads."""

        extra_payloads = extra_payloads or []
        await self.async_send_siduses(
            [*power_on_payloads(), *extra_payloads],
            first_payload_delay=_POWER_SETTLE_DELAY if extra_payloads else 0.0,
        )
        self._desired_power = True

    async def async_turn_off(self) -> None:
        """Send the Sidus power-off payload."""

        await self.async_send_siduses(power_off_payloads())
        self._desired_power = False

    async def async_set_brightness_cct(
        self, *, brightness: int, kelvin: int, power_on: bool = False
    ) -> None:
        """Send the Telink CCT payload carrying brightness and CCT."""

        brightness = _clamp_brightness(brightness)
        kelvin = _clamp_kelvin(kelvin)
        sidus_intensity = round(brightness / 255 * 1000)
        payload = brightness_cct_payload(brightness=brightness, kelvin=kelvin)
        _LOGGER.debug(
            "Combined Sidus request brightness_ha=%s cct_kelvin=%s "
            "sidus_intensity=%s sidus=%s access=%s power_on=%s",
            brightness,
            kelvin,
            sidus_intensity,
            payload.hex(" "),
            access_payload(payload).hex(" "),
            power_on,
        )

        await self.async_send_siduses(
            cct_payloads(
                brightness=brightness,
                kelvin=kelvin,
                power_on=power_on,
            ),
            first_payload_delay=_POWER_SETTLE_DELAY if power_on else 0.0,
        )

        self._desired_power = True
        self._desired_brightness = brightness
        self._desired_color_temp_kelvin = kelvin
        self._desired_active_color_mode = COLOR_MODE_COLOR_TEMP

    async def async_set_brightness(
        self, *, brightness: int, power_on: bool = False
    ) -> None:
        """Send the Telink brightness-only payload."""

        brightness = _clamp_brightness(brightness)
        sidus_intensity = round(brightness / 255 * 1000)
        payloads = brightness_payloads(brightness=brightness, power_on=power_on)
        _LOGGER.debug(
            "Brightness Sidus request brightness_ha=%s sidus_intensity=%s "
            "sidus=%s access=%s power_on=%s",
            brightness,
            sidus_intensity,
            payloads[-1].hex(" "),
            access_payload(payloads[-1]).hex(" "),
            power_on,
        )

        await self.async_send_siduses(
            payloads,
            first_payload_delay=_POWER_SETTLE_DELAY if power_on else 0.0,
        )

        self._desired_power = True
        self._desired_brightness = brightness

    async def async_set_cct(
        self, *, brightness: int, kelvin: int, power_on: bool = False
    ) -> None:
        """Send the Telink CCT payload while preserving brightness."""

        await self.async_set_brightness_cct(
            brightness=brightness,
            kelvin=kelvin,
            power_on=power_on,
        )

    async def async_set_hsi(
        self,
        *,
        brightness: int,
        hs_color: tuple[float, float],
        power_on: bool = False,
    ) -> None:
        """Send the Telink HSI payload while preserving hue/saturation."""

        brightness = _clamp_brightness(brightness)
        hue, saturation = _clamp_hs(hs_color)
        sidus_intensity = round(brightness / 255 * 1000)
        payloads = hsi_payloads(
            brightness=brightness,
            hue=hue,
            saturation=saturation,
            power_on=power_on,
        )
        _LOGGER.debug(
            "HSI Sidus request brightness_ha=%s hue=%s saturation=%s "
            "sidus_intensity=%s sidus=%s access=%s power_on=%s",
            brightness,
            hue,
            saturation,
            sidus_intensity,
            payloads[-1].hex(" "),
            access_payload(payloads[-1]).hex(" "),
            power_on,
        )

        await self.async_send_siduses(
            payloads,
            first_payload_delay=_POWER_SETTLE_DELAY if power_on else 0.0,
        )

        self._desired_power = True
        self._desired_brightness = brightness
        self._desired_hs_color = (hue, saturation)
        self._desired_active_color_mode = COLOR_MODE_HS

    async def async_send_siduses(
        self, sidus_payloads: list[bytes], *, first_payload_delay: float = 0.0
    ) -> None:
        """Write one or more encrypted Sidus payloads through configured transport."""

        started_at = time.time()
        self._last_command = {
            "started_at": started_at,
            "light_name": self.name,
            "connection_address": self.proxy_address,
            "node_address": self._node_address,
            "payload_count": len(sidus_payloads),
            "payloads": [payload.hex(" ") for payload in sidus_payloads],
            "status": "pending",
            "success": None,
        }
        self._last_physical_validation = {
            "available": False,
            "reason": "no light-level ACK/readback implemented",
            "validated_at": None,
        }
        _LOGGER.debug(
            "Sidus light command light=%s light_node=0x%04x "
            "connection_selection=%s connection_address=%s dst=0x%04x",
            self.name,
            self._node_address,
            self.proxy_selection,
            self.proxy_address or "auto",
            self._node_address,
        )
        try:
            await self._mesh_network.async_send_siduses(
                sidus_payloads,
                node_address=self._node_address,
                fixture_name=self.name,
                fixture_mac=self.ble_mac,
                first_payload_delay=first_payload_delay,
            )
        except Exception as err:
            self._mark_command_failure(err)
            self._last_command.update(
                {
                    "completed_at": time.time(),
                    "status": "failed",
                    "success": False,
                    "error": repr(err),
                }
            )
            raise
        self._last_command.update(
            {
                "completed_at": time.time(),
                "status": "proxy_write_complete",
                "success": True,
                "transport_state": self.transport_metrics.get("state"),
            }
        )

    def _handle_power_info_update(self, message: dict[str, Any]) -> None:
        power_info = message.get("sidus_power_info")
        if power_info is None:
            return
        if int(getattr(power_info, "source_address", -1)) != self._node_address:
            return
        if not self.battery_capable:
            return

        percentage = int(power_info.battery_percentage)
        mode = str(power_info.power_supply_mode)
        if mode == "ac" and percentage == 0:
            return

        self._battery_percentage = max(0, min(100, percentage))
        self._battery_power_info = {
            "power_supply_mode": mode,
            "battery_time_minutes": int(power_info.battery_time_minutes),
            "battery_percentage": self._battery_percentage,
            "battery_voltage": int(power_info.battery_voltage),
            "external_voltage": int(power_info.external_voltage),
            "command_type": int(power_info.command_type),
            "operation_type": int(power_info.operation_type),
            "source_address": int(power_info.source_address),
            "destination_address": int(power_info.destination_address),
            "sequence": int(power_info.sequence),
            "received_at": float(message.get("received_at", time.time())),
        }
        _LOGGER.debug(
            "Sidus battery update light=%s node=0x%04x mode=%s battery=%s "
            "time_minutes=%s",
            self.name,
            self._node_address,
            mode,
            self._battery_percentage,
            power_info.battery_time_minutes,
        )
        self._notify_battery_callbacks()

    def _mark_command_failure(self, err: Exception) -> None:
        was_available = self.is_available
        _LOGGER.debug(
            "Sidus light command failed light=%s error=%r",
            self.name,
            err,
        )
        if self.is_available != was_available:
            self._notify_availability_callbacks()

    def _fixture_presence_ok(self) -> bool:
        if not self._presence_checking_enabled:
            return True
        if self._last_advertisement_seen is None:
            return False
        return (
            time.time() - self._last_advertisement_seen
        ) <= self._presence_unavailable_after

    def _schedule_presence_expiry(self) -> None:
        self._cancel_presence_expiry()
        if (
            not self._presence_checking_enabled
            or self._last_advertisement_seen is None
        ):
            return
        try:
            from homeassistant.helpers.event import async_call_later
        except Exception:
            return
        delay = max(
            0.0,
            self._presence_unavailable_after
            - (time.time() - self._last_advertisement_seen),
        )
        if delay <= 0:
            return

        def _expire(_now: Any) -> None:
            self._presence_expire_unsubscribe = None
            self._seed_last_advertisement_from_cache()
            self._notify_availability_callbacks()

        self._presence_expire_unsubscribe = async_call_later(
            self.hass,
            delay,
            _expire,
        )

    def _cancel_presence_expiry(self) -> None:
        unsubscribe = self._presence_expire_unsubscribe
        self._presence_expire_unsubscribe = None
        if callable(unsubscribe):
            unsubscribe()

    def _notify_availability_callbacks(self) -> None:
        loop = getattr(getattr(self, "hass", None), "loop", None)
        for callback in tuple(self._availability_callbacks):
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(callback)
            else:
                callback()

    def _notify_battery_callbacks(self) -> None:
        loop = getattr(getattr(self, "hass", None), "loop", None)
        for callback in tuple(self._battery_callbacks):
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(callback)
            else:
                callback()


def _sequence_storage_key(net_key: bytes, source_address: int, iv_index: int) -> str:
    digest = hashlib.sha1(
        net_key + source_address.to_bytes(2, "big") + iv_index.to_bytes(4, "big")
    ).hexdigest()
    return f"sequence_{digest[:16]}"


def _advertisement_seen_at(service_info: Any) -> float:
    """Return the advertisement's wall-clock timestamp when HA provides one."""

    advertisement_monotonic = getattr(service_info, "time", None)
    if not isinstance(advertisement_monotonic, (int, float)):
        return time.time()
    age = max(0.0, time.monotonic() - float(advertisement_monotonic))
    return time.time() - age


def mesh_network_key(entry: ConfigEntry, fixture: dict[str, Any]) -> str:
    """Return stable runtime key for entries sharing one mesh proxy."""

    data = {**entry.data, **fixture}
    net_key = normalize_hex_key(data[CONF_NET_KEY], field="network key")
    app_key = normalize_hex_key(data[CONF_APP_KEY], field="app key")
    source_address = int(data.get(CONF_SOURCE_ADDRESS, DEFAULT_SOURCE_ADDRESS))
    proxy_mac = (_entry_proxy_mac(entry, data) or "auto").lower()
    digest = hashlib.sha256(
        net_key
        + app_key
        + source_address.to_bytes(2, "big")
        + proxy_mac.encode("utf-8")
    ).hexdigest()
    return f"mesh_{digest[:24]}"


def get_mesh_network(
    hass: HomeAssistant,
    entry: ConfigEntry,
    fixtures: list[dict[str, Any]],
    *,
    context_entries: list[ConfigEntry],
    context_fixtures: list[dict[str, Any]],
) -> SidusMeshNetwork:
    """Return one shared runtime for all config entries in a mesh."""

    key = mesh_network_key(entry, fixtures[0])
    networks: dict[str, SidusMeshNetwork] = hass.data.setdefault(_MESH_NETWORKS, {})
    network = networks.get(key)
    if network is None:
        network = SidusMeshNetwork(
            hass,
            entry,
            context_fixtures,
            entries=context_entries,
        )
        networks[key] = network
    network.attach_entry(entry, fixtures)
    return network


async def async_release_mesh_network(
    hass: HomeAssistant, entry: ConfigEntry, network: SidusMeshNetwork
) -> None:
    """Release shared runtime after one config entry unloads."""

    if not network.detach_entry(entry.entry_id):
        return
    networks: dict[str, SidusMeshNetwork] = hass.data.get(_MESH_NETWORKS, {})
    for key, candidate in tuple(networks.items()):
        if candidate is network:
            networks.pop(key, None)
            break
    await network.async_close()


def _configured_proxy_mac(
    entries: list[ConfigEntry], data: dict[str, Any]
) -> str:
    """Return optional manual proxy MAC with legacy option fallback."""

    for entry in entries:
        value = _entry_proxy_mac(entry, entry.data)
        if value:
            return value
    if entries:
        return ""
    for field in (CONF_PROXY_MAC, CONF_PROXY_ADDRESS):
        if field in data:
            return str(data.get(field) or "").strip()
    return ""


def _entry_proxy_mac(entry: ConfigEntry, data: dict[str, Any]) -> str:
    """Return one entry's effective proxy MAC, respecting blank option overrides."""

    for source in (entry.options, entry.data, data):
        for field in (CONF_PROXY_MAC, CONF_PROXY_ADDRESS):
            if field in source:
                return str(source.get(field) or "").strip()
    return ""


def _entry_bool(entry: ConfigEntry, field: str, default: bool) -> bool:
    """Return one boolean option with data fallback."""

    for source in (entry.options, entry.data):
        if field in source:
            return _bool_value(source[field], default=default)
    return default


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("", "0", "false", "off", "no"):
            return False
        if normalized in ("1", "true", "on", "yes"):
            return True
    return bool(value)


def _configured_proxy_candidates(entries: list[ConfigEntry]) -> list[str]:
    """Return persisted proxy candidate addresses across matching entries."""

    candidates: list[str] = []
    for entry in entries:
        values = entry.data.get(CONF_PROXY_CANDIDATES)
        if isinstance(values, (list, tuple)):
            candidates.extend(str(value) for value in values)
    return candidates


def _mesh_proxy_candidates(
    fixtures: list[dict[str, Any]],
    configured_candidates: Any,
    manual_proxy_mac: str,
) -> tuple[str, ...]:
    """Return ordered manual/configured/fixture proxy candidates."""

    candidates: list[str] = [manual_proxy_mac]
    if isinstance(configured_candidates, (list, tuple)):
        candidates.extend(str(value) for value in configured_candidates)
    for fixture in fixtures:
        candidates.extend(
            (
                str(fixture.get(CONF_BLE_MAC) or ""),
                str(fixture.get(CONF_ADDRESS) or ""),
            )
        )
    return tuple(
        value
        for value in dict.fromkeys(candidate.strip() for candidate in candidates)
        if value
    )


def _fixture_identity(fixture: dict[str, Any]) -> str:
    """Return stable identity for merging fixture destinations."""

    return str(
        fixture.get(CONF_BLE_MAC)
        or fixture.get(CONF_DEVICE_UUID)
        or f"node-{int(fixture[CONF_NODE_ADDRESS]):04x}"
    ).lower()


def _address_matches(address: str, candidates: tuple[str, ...]) -> bool:
    normalized = address.lower()
    return any(normalized == candidate.lower() for candidate in candidates)


def _utc_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="milliseconds")


def _hex_byte(value: Any) -> str:
    if value is None:
        return "none"
    return f"0x{int(value) & 0xFF:02x}"


def _clamp_brightness(brightness: int) -> int:
    return max(0, min(255, int(brightness)))


def _clamp_kelvin(kelvin: int) -> int:
    return max(MIN_COLOR_TEMP_KELVIN, min(MAX_COLOR_TEMP_KELVIN, int(kelvin)))


def _clamp_hs(hs_color: tuple[float, float]) -> tuple[float, float]:
    hue, saturation = hs_color
    return (
        max(0.0, min(360.0, float(hue))),
        max(0.0, min(100.0, float(saturation))),
    )


def _optional_percentage(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return None
