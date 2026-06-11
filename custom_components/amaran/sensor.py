"""Diagnostic sensors for Amaran Sidus transports."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import AmaranSidusClient
from .const import DOMAIN, MANUFACTURER
from .fixtures import fixture_device_identifier

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Amaran Sidus diagnostic sensor entities."""

    clients: list[AmaranSidusClient] = hass.data[DOMAIN][entry.entry_id]
    sensors: list[SensorEntity] = [
        AmaranSidusTransportSensor(client) for client in clients
    ]
    sensors.extend(
        AmaranSidusBatterySensor(client)
        for client in clients
        if client.battery_capable
    )
    async_add_entities(sensors)


class AmaranSidusTransportSensor(SensorEntity):
    """Expose BLE warm-up/transport diagnostics."""

    _attr_has_entity_name = True
    _attr_name = "Transport"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_should_poll = True

    def __init__(self, client: AmaranSidusClient) -> None:
        self._client = client
        self._attr_unique_id = transport_sensor_unique_id(client)

    @property
    def native_value(self) -> str:
        """Return transport state."""

        return self._client.transport_state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return transport timings and cached BLE path."""

        metrics = self._client.transport_metrics
        return {
            "last_connect_time": self._client.last_connect_time,
            "last_write_latency_ms": self._client.last_write_latency_ms,
            "last_write_time": metrics.get("last_write_time"),
            "connected": self._client.connected,
            "connection_mode": self._client.transport_mode,
            "connection_selection": self._client.proxy_selection,
            "connection_address": self._client.proxy_address,
            "node_address": self._client.node_address,
            "light_reachable": self._client.fixture_reachable,
            "light_stale_seconds": self._client.fixture_stale_seconds,
            "light_advertisement_availability": self._client.presence_checking_enabled,
            "light_stale_after_seconds": self._client.presence_unavailable_after,
            "last_advertisement_seen": self._client.last_advertisement_seen,
            "last_advertisement_address": self._client.last_advertisement_address,
            "last_advertisement_rssi": self._client.last_advertisement_rssi,
            "last_connection_advertisement_seen": self._client.last_proxy_advertisement_seen,
            "queue_depth": metrics.get("queue_depth"),
            "reconnect_count": metrics.get("reconnect_count"),
            "connect_ms": metrics.get("connect_ms"),
            "bluetooth_lookup_ms": metrics.get("bluetooth_lookup_ms"),
            "service_discovery_ms": metrics.get("service_discovery_ms"),
            "characteristic_resolve_ms": metrics.get("characteristic_resolve_ms"),
            "proxy_in_found": metrics.get("proxy_in_found"),
            "selected_connection_address": metrics.get("selected_proxy_address"),
            "selected_connection_rssi": metrics.get("selected_proxy_rssi"),
            "last_error": metrics.get("last_error"),
            "last_bluetooth_device": self._client.last_bluetooth_device,
            "last_write": self._client.last_write,
            "last_command": self._client.last_command,
            "last_physical_validation": self._client.last_physical_validation,
        }

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device registry info."""

        info: dict[str, Any] = {
            "identifiers": {(DOMAIN, fixture_device_identifier(self._client.data))},
            "manufacturer": MANUFACTURER,
            "model": self._client.model,
            "name": self._client.name,
        }
        bluetooth_address = self._client.ble_mac or self._client.address
        if ":" in bluetooth_address:
            info["connections"] = {(dr.CONNECTION_BLUETOOTH, bluetooth_address)}
        return info


class AmaranSidusBatterySensor(SensorEntity):
    """Expose real battery percentage when the protocol provides it."""

    _attr_has_entity_name = True
    _attr_name = "Battery"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, client: AmaranSidusClient) -> None:
        self._client = client
        self._attr_unique_id = battery_sensor_unique_id(client)
        self._unsubscribe_battery: Any | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to real decoded battery updates."""

        self._unsubscribe_battery = self._client.subscribe_battery(
            self._handle_battery_update
        )
        async_on_remove = getattr(self, "async_on_remove", None)
        if callable(async_on_remove):
            async_on_remove(self._unsubscribe_battery)

    @property
    def native_value(self) -> int | None:
        """Return battery percentage only when known."""

        return self._client.battery_percentage

    @property
    def available(self) -> bool:
        """Return false when no real battery value is known."""

        return self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return decoded packet diagnostics when known."""

        return self._client.battery_power_info

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device registry info."""

        info: dict[str, Any] = {
            "identifiers": {(DOMAIN, fixture_device_identifier(self._client.data))},
            "manufacturer": MANUFACTURER,
            "model": self._client.model,
            "name": self._client.name,
        }
        bluetooth_address = self._client.ble_mac or self._client.address
        if ":" in bluetooth_address:
            info["connections"] = {(dr.CONNECTION_BLUETOOTH, bluetooth_address)}
        return info

    def _handle_battery_update(self) -> None:
        self.async_write_ha_state()


def transport_sensor_unique_id(client: AmaranSidusClient) -> str:
    """Return stable transport diagnostic sensor ID."""

    return (
        f"{client.ble_mac or client.address}_node_{client.node_address}_"
        f"src_{client.source_address}_transport"
    )


def battery_sensor_unique_id(client: AmaranSidusClient) -> str:
    """Return stable battery diagnostic sensor ID."""

    return (
        f"{client.ble_mac or client.address}_node_{client.node_address}_"
        f"src_{client.source_address}_battery"
    )


async def async_disable_transport_sensors(
    hass: HomeAssistant, clients: list[AmaranSidusClient]
) -> None:
    """Disable existing and new transport sensors after platform setup."""

    registry = er.async_get(hass)
    pending = {transport_sensor_unique_id(client) for client in clients}
    for _attempt in range(10):
        for unique_id in tuple(pending):
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
            if entity_id is None:
                continue
            updated = registry.async_update_entity(
                entity_id,
                disabled_by=er.RegistryEntryDisabler.INTEGRATION,
                entity_category=EntityCategory.DIAGNOSTIC,
            )
            if updated.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
                _LOGGER.debug(
                    "Disabled internal Sidus connection diagnostic entity_id=%s",
                    entity_id,
                )
                pending.discard(unique_id)
        if not pending:
            return
        await asyncio.sleep(0.5)
