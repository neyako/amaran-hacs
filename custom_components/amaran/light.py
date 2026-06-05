"""Light entity for Amaran Sidus devices."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import inspect
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .client import AmaranSidusClient
from .const import (
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_HS,
    DEFAULT_COLOR_TEMP_KELVIN,
    DOMAIN,
    MANUFACTURER,
    MAX_COLOR_TEMP_KELVIN,
    MIN_COLOR_TEMP_KELVIN,
)
from .state import (
    COMMAND_BRIGHTNESS,
    COMMAND_CCT,
    COMMAND_HSI,
    COMMAND_POWER,
    DEFAULT_HS_COLOR,
    FixtureCachedState,
    plan_turn_on,
    turn_off_state,
)
from .fixtures import fixture_device_identifier
from .state_store import AmaranLightStateStore

_LOGGER = logging.getLogger(__name__)
_ATTR_COLOR_MODE = "color_mode"
_ICON_CCT = "mdi:lightbulb-on-outline"
_ICON_FALLBACK = "mdi:lightbulb"
_ICON_RGB = "mdi:palette"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Amaran Sidus light entity."""

    clients: list[AmaranSidusClient] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AmaranSidusLight(client, entry) for client in clients])


class AmaranSidusLight(LightEntity, RestoreEntity):
    """Optimistic Amaran Ace light over encrypted Sidus mesh proxy."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = True
    _attr_min_color_temp_kelvin = MIN_COLOR_TEMP_KELVIN
    _attr_max_color_temp_kelvin = MAX_COLOR_TEMP_KELVIN

    def __init__(self, client: AmaranSidusClient, entry: ConfigEntry) -> None:
        self._client = client
        self._entry = entry
        self._attr_unique_id = (
            f"{client.ble_mac or client.address}_node_{client.node_address}_"
            f"src_{client.source_address}"
        )
        self._attr_supported_color_modes = set()
        if COLOR_MODE_BRIGHTNESS in client.supported_color_modes:
            self._attr_supported_color_modes.add(ColorMode.BRIGHTNESS)
        if COLOR_MODE_COLOR_TEMP in client.supported_color_modes:
            self._attr_supported_color_modes.add(ColorMode.COLOR_TEMP)
        if client.supports_hs:
            self._attr_supported_color_modes.add(ColorMode.HS)
        if not self._attr_supported_color_modes:
            self._attr_supported_color_modes.add(ColorMode.COLOR_TEMP)
        self._attr_icon = _icon_for_client(client)
        _LOGGER.debug(
            "Light %s model=%s capabilities=%s supported_color_modes=%s",
            client.name,
            client.model,
            client.capabilities,
            self._attr_supported_color_modes,
        )
        self._is_on = bool(client.desired_power)
        self._brightness = (
            client.desired_brightness if client.desired_brightness is not None else 255
        )
        self._color_temp_kelvin = (
            client.desired_color_temp_kelvin
            if client.desired_color_temp_kelvin is not None
            else DEFAULT_COLOR_TEMP_KELVIN
        )
        self._hs_color = client.desired_hs_color or DEFAULT_HS_COLOR
        self._active_color_mode = (
            client.desired_active_color_mode
            if client.supports_color_temp
            else COLOR_MODE_BRIGHTNESS
        )
        self._assumed_state = True
        self._state_store: AmaranLightStateStore | None = None
        self._status_unsubscribe: Callable[[], None] | None = None
        self._availability_unsubscribe: Callable[[], None] | None = None
        self._sync_attrs()

    async def async_added_to_hass(self) -> None:
        """Restore state after a Home Assistant restart without light writes."""

        added = getattr(super(), "async_added_to_hass", None)
        if callable(added):
            result = added()
            if inspect.isawaitable(result):
                await result

        self._state_store = AmaranLightStateStore(self.hass, self._client)
        stored_state = await self._state_store.async_load()
        if stored_state is not None:
            self._restore_from_persistent_state(stored_state)
        else:
            await self._restore_from_ha_state()

        self._client.set_cached_state(
            power=self._is_on,
            brightness=self._brightness,
            kelvin=self._color_temp_kelvin,
            hs_color=self._hs_color,
            active_color_mode=self._active_color_mode,
        )
        self._status_unsubscribe = self._client.subscribe_status(
            self._handle_status_update
        )
        subscribe_availability = getattr(self._client, "subscribe_availability", None)
        if callable(subscribe_availability):
            self._availability_unsubscribe = subscribe_availability(
                self._handle_availability_update
            )
        async_on_remove = getattr(self, "async_on_remove", None)
        if callable(async_on_remove) and self._status_unsubscribe is not None:
            async_on_remove(self._status_unsubscribe)
        if callable(async_on_remove) and self._availability_unsubscribe is not None:
            async_on_remove(self._availability_unsubscribe)
        self._sync_attrs()

    @property
    def assumed_state(self) -> bool:
        """Return true until a real status notification confirms the light."""

        return self._assumed_state

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

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""

        return self._is_on

    @property
    def available(self) -> bool:
        """Return true when proxy and fixture reachability checks pass."""

        return self._client.is_available

    @property
    def brightness(self) -> int:
        """Return current optimistic brightness."""

        return self._brightness

    @property
    def color_mode(self) -> ColorMode:
        """Return current color mode."""

        if self._active_color_mode == COLOR_MODE_HS and self._client.supports_hs:
            return ColorMode.HS
        if not self._client.supports_color_temp:
            return ColorMode.BRIGHTNESS
        return ColorMode.COLOR_TEMP

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return current optimistic color temperature."""

        if self.color_mode != ColorMode.COLOR_TEMP:
            return None
        return self._color_temp_kelvin

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return current optimistic HS color."""

        if not self._client.supports_hs:
            return None
        if self.color_mode != ColorMode.HS:
            return None
        return self._hs_color

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light and optionally set brightness/color."""

        self._raise_if_unavailable()
        plan = plan_turn_on(
            self._cached_state(),
            supports_hs=self._client.supports_hs,
            supports_color_temp=self._client.supports_color_temp,
            brightness=kwargs.get(ATTR_BRIGHTNESS),
            kelvin=kwargs.get(ATTR_COLOR_TEMP_KELVIN),
            hs_color=kwargs.get(ATTR_HS_COLOR),
        )

        _LOGGER.debug(
            "HA turn_on request requested_brightness=%s requested_cct_kelvin=%s "
            "requested_hs=%s resolved_brightness=%s resolved_cct_kelvin=%s "
            "resolved_hs=%s power_on=%s command=%s active_mode=%s",
            kwargs.get(ATTR_BRIGHTNESS),
            kwargs.get(ATTR_COLOR_TEMP_KELVIN),
            kwargs.get(ATTR_HS_COLOR),
            plan.state.brightness,
            plan.state.color_temp_kelvin,
            plan.state.hs_color,
            plan.power_on,
            plan.command,
            plan.state.active_color_mode,
        )

        if plan.command == COMMAND_HSI:
            await self._client.async_set_hsi(
                brightness=plan.state.brightness,
                hs_color=plan.state.hs_color,
                power_on=plan.power_on,
            )
        elif plan.command == COMMAND_CCT:
            await self._client.async_set_cct(
                brightness=plan.state.brightness,
                kelvin=plan.state.color_temp_kelvin,
                power_on=plan.power_on,
            )
        elif plan.command == COMMAND_BRIGHTNESS:
            await self._client.async_set_brightness(
                brightness=plan.state.brightness,
                power_on=plan.power_on,
            )
        elif plan.command == COMMAND_POWER:
            await self._client.async_turn_on()
        await self._async_apply_state(plan.state, assumed_state=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""

        self._raise_if_unavailable()
        _LOGGER.debug("HA turn_off")
        await self._client.async_turn_off()
        await self._async_apply_state(
            turn_off_state(self._cached_state()),
            assumed_state=True,
        )

    def _cached_state(self) -> FixtureCachedState:
        return FixtureCachedState(
            power=self._is_on,
            brightness=self._brightness,
            color_temp_kelvin=self._color_temp_kelvin,
            hs_color=self._hs_color,
            active_color_mode=self._active_color_mode,
        )

    async def _async_apply_state(
        self, state: FixtureCachedState, *, assumed_state: bool
    ) -> None:
        self._apply_state(state, assumed_state=assumed_state)
        await self._async_save_persistent_state()

    def _apply_state(
        self, state: FixtureCachedState, *, assumed_state: bool
    ) -> None:
        self._is_on = state.power
        self._brightness = state.brightness
        self._color_temp_kelvin = state.color_temp_kelvin
        self._hs_color = state.hs_color
        self._active_color_mode = state.active_color_mode
        self._assumed_state = assumed_state
        self._client.set_cached_state(
            power=state.power,
            brightness=state.brightness,
            kelvin=state.color_temp_kelvin,
            hs_color=state.hs_color,
            active_color_mode=state.active_color_mode,
        )
        self._sync_attrs()

    def _raise_if_unavailable(self) -> None:
        if self.available:
            return
        raise HomeAssistantError(
            f"{self._client.name} connection is {self._client.transport_state}"
        )

    def _sync_attrs(self) -> None:
        """Keep Home Assistant's cached entity attrs aligned with mode."""

        self._attr_is_on = self._is_on
        self._attr_assumed_state = self._assumed_state
        self._attr_brightness = self._brightness
        self._attr_color_mode = self.color_mode
        if self._attr_color_mode == ColorMode.HS:
            self._attr_hs_color = self._hs_color
            self._attr_color_temp_kelvin = None
        elif self._attr_color_mode == ColorMode.BRIGHTNESS:
            self._attr_hs_color = None
            self._attr_color_temp_kelvin = None
        else:
            self._attr_hs_color = None
            self._attr_color_temp_kelvin = self._color_temp_kelvin

    async def _restore_from_ha_state(self) -> None:
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        self._is_on = last_state.state == STATE_ON
        if (brightness := last_state.attributes.get(ATTR_BRIGHTNESS)) is not None:
            self._brightness = _clamp_brightness(brightness)
        if (kelvin := last_state.attributes.get(ATTR_COLOR_TEMP_KELVIN)) is not None:
            self._color_temp_kelvin = _clamp_kelvin(kelvin)
        if (hs_color := last_state.attributes.get(ATTR_HS_COLOR)) is not None:
            self._hs_color = _clamp_hs(hs_color)
        if (color_mode := last_state.attributes.get(_ATTR_COLOR_MODE)) in (
            ColorMode.BRIGHTNESS,
            ColorMode.COLOR_TEMP,
            ColorMode.HS,
            COLOR_MODE_BRIGHTNESS,
            COLOR_MODE_COLOR_TEMP,
            COLOR_MODE_HS,
        ):
            self._active_color_mode = _ha_mode_to_cached(color_mode)
        self._assumed_state = True

    def _restore_from_persistent_state(self, data: dict[str, Any]) -> None:
        self._is_on = bool(data.get("power", self._is_on))
        if (brightness := data.get("brightness")) is not None:
            self._brightness = _clamp_brightness(brightness)
        if (kelvin := data.get("color_temp_kelvin")) is not None:
            self._color_temp_kelvin = _clamp_kelvin(kelvin)
        if (hs_color := data.get("hs_color")) is not None:
            self._hs_color = _clamp_hs(hs_color)
        if (color_mode := data.get("color_mode")) is not None:
            self._active_color_mode = _ha_mode_to_cached(color_mode)
        self._assumed_state = bool(data.get("assumed_state", True))

    async def _async_save_persistent_state(self) -> None:
        if self._state_store is None:
            return
        await self._state_store.async_save(
            self._cached_state(),
            assumed_state=self._assumed_state,
        )

    def _handle_status_update(self, status: dict[str, Any]) -> None:
        state = FixtureCachedState(
            power=bool(status["power"]),
            brightness=_clamp_brightness(status["brightness"]),
            color_temp_kelvin=_clamp_kelvin(
                status.get("color_temp_kelvin") or self._color_temp_kelvin
            ),
            hs_color=_clamp_hs(status.get("hs_color") or self._hs_color),
            active_color_mode=_ha_mode_to_cached(status["color_mode"]),
        )
        self._apply_state(state, assumed_state=False)
        self._schedule_state_save()
        write_state = getattr(self, "async_write_ha_state", None)
        if callable(write_state):
            write_state()

    def _handle_availability_update(self) -> None:
        write_state = getattr(self, "async_write_ha_state", None)
        if callable(write_state):
            write_state()

    def _schedule_state_save(self) -> None:
        if self._state_store is None:
            return
        task = self._async_save_persistent_state()
        create_task = getattr(getattr(self, "hass", None), "async_create_task", None)
        if callable(create_task):
            create_task(task)
        else:
            asyncio.create_task(task)


def _clamp_brightness(brightness: Any) -> int:
    return max(0, min(255, int(brightness)))


def _clamp_kelvin(kelvin: Any) -> int:
    return max(MIN_COLOR_TEMP_KELVIN, min(MAX_COLOR_TEMP_KELVIN, int(kelvin)))


def _clamp_hs(hs_color: Any) -> tuple[float, float]:
    hue, saturation = hs_color
    return (
        max(0.0, min(360.0, float(hue))),
        max(0.0, min(100.0, float(saturation))),
    )


def _ha_mode_to_cached(color_mode: Any) -> str:
    if str(color_mode) == str(ColorMode.HS) or color_mode == COLOR_MODE_HS:
        return COLOR_MODE_HS
    if (
        str(color_mode) == str(ColorMode.BRIGHTNESS)
        or color_mode == COLOR_MODE_BRIGHTNESS
    ):
        return COLOR_MODE_BRIGHTNESS
    return COLOR_MODE_COLOR_TEMP


def _icon_for_client(client: AmaranSidusClient) -> str:
    if client.supports_hs:
        return _ICON_RGB
    if client.supports_color_temp:
        return _ICON_CCT
    return _ICON_FALLBACK
