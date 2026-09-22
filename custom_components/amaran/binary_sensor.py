"""External power status from actual Sidus power reports."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import AmaranSidusClient
from .const import DOMAIN
from .fixtures import fixture_device_identifier


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        AmaranExternalPowerSensor(client)
        for client in hass.data[DOMAIN][entry.entry_id]
        if client.battery_capable
    )


class AmaranExternalPowerSensor(BinarySensorEntity):
    """Show external supply presence; this is not an active-charging claim."""

    _attr_has_entity_name = True
    _attr_name = "External power"
    _attr_device_class = BinarySensorDeviceClass.PLUG
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, client: AmaranSidusClient) -> None:
        self._client = client
        self._attr_unique_id = (
            f"{client.ble_mac or client.address}_node_{client.node_address}_"
            f"src_{client.source_address}_external_power"
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.subscribe_battery(self._handle_update))
        self.async_on_remove(self._client.subscribe_availability(self._handle_update))

    @property
    def is_on(self) -> bool | None:
        info = self._client.battery_power_info
        return None if info is None else info["external_voltage"] > 0

    @property
    def available(self) -> bool:
        return self._client.is_available and self.is_on is not None

    @property
    def device_info(self) -> dict[str, Any]:
        return {"identifiers": {(DOMAIN, fixture_device_identifier(self._client.data))}}

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
