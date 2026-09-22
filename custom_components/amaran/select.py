"""Native effect chooser backed by the light entity's existing control path."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_EFFECT, EFFECT_OFF
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .client import AmaranSidusClient
from .const import DOMAIN
from .fixtures import fixture_device_identifier


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add a chooser for every catalog-supported color light with effects."""

    async_add_entities(
        AmaranEffectSelect(client)
        for client in hass.data[DOMAIN][entry.entry_id]
        if client.supported_effects
    )


class AmaranEffectSelect(SelectEntity):
    """Mirror the light's effect without a second command/state implementation."""

    _attr_has_entity_name = True
    _attr_name = "Effect preset"
    _attr_icon = "mdi:creation"
    _attr_should_poll = False

    def __init__(self, client: AmaranSidusClient) -> None:
        self._client = client
        self._light_unique_id = (
            f"{client.ble_mac or client.address}_node_{client.node_address}_"
            f"src_{client.source_address}"
        )
        self._attr_unique_id = f"{self._light_unique_id}_effect"
        self._attr_options = [EFFECT_OFF, *client.supported_effects]
        self._light_entity_id: str | None = None

    async def async_added_to_hass(self) -> None:
        # The light platform is set up first, so registry lookup also honors renames.
        self._light_entity_id = er.async_get(self.hass).async_get_entity_id(
            "light", DOMAIN, self._light_unique_id
        )
        if self._light_entity_id is not None:
            self.async_on_remove(async_track_state_change_event(
                self.hass, [self._light_entity_id], self._handle_light_update,
            ))

    @property
    def available(self) -> bool:
        state = self.hass.states.get(self._light_entity_id) if self._light_entity_id else None
        return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)

    @property
    def current_option(self) -> str | None:
        state = self.hass.states.get(self._light_entity_id) if self._light_entity_id else None
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        if state.state == STATE_OFF:
            return EFFECT_OFF
        effect = state.attributes.get(ATTR_EFFECT) or EFFECT_OFF
        return effect if effect in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            raise HomeAssistantError(f"Unsupported effect: {option}")
        if not self.available:
            raise HomeAssistantError("The light is unavailable")
        if option == EFFECT_OFF and self.hass.states.get(self._light_entity_id).state == STATE_OFF:
            return
        await self.hass.services.async_call(
            "light", "turn_on",
            {"entity_id": self._light_entity_id, ATTR_EFFECT: option},
            blocking=True, context=self._context,
        )

    @property
    def device_info(self) -> dict[str, Any]:
        return {"identifiers": {(DOMAIN, fixture_device_identifier(self._client.data))}}

    @callback
    def _handle_light_update(self, _event: Any) -> None:
        self.async_write_ha_state()
