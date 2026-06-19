"""Green/magenta tint control for Amaran CCT lights."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberMode,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import AmaranSidusClient
from .const import DOMAIN, MANUFACTURER
from .fixtures import fixture_device_identifier


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the green/magenta number for CCT-capable lights."""

    clients: list[AmaranSidusClient] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AmaranGreenMagentaNumber(client)
        for client in clients
        if client.supports_color_temp
    )


class AmaranGreenMagentaNumber(RestoreNumber, NumberEntity):
    """Adjust the green/magenta point applied to CCT commands (-10..+10)."""

    _attr_has_entity_name = True
    _attr_name = "Green / magenta"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = -10
    _attr_native_max_value = 10
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:tune"

    def __init__(self, client: AmaranSidusClient) -> None:
        self._client = client
        self._attr_unique_id = (
            f"{client.ble_mac or client.address}_node_{client.node_address}_"
            f"src_{client.source_address}_green_magenta"
        )

    async def async_added_to_hass(self) -> None:
        """Restore the last tint without sending a command at startup."""

        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._client.set_green_magenta_cached(int(last.native_value))

    @property
    def available(self) -> bool:
        """Match the light's transport-based availability."""

        return self._client.is_available

    @property
    def native_value(self) -> float:
        """Return the cached green/magenta point."""

        return float(self._client.green_magenta)

    async def async_set_native_value(self, value: float) -> None:
        """Apply a new green/magenta point."""

        await self._client.async_set_green_magenta(int(value))
        self.async_write_ha_state()

    @property
    def device_info(self) -> dict[str, Any]:
        """Attach to the same device as the light."""

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
