"""Pure optimistic light state planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import (
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_HS,
    DEFAULT_COLOR_TEMP_KELVIN,
    MAX_COLOR_TEMP_KELVIN,
    MIN_COLOR_TEMP_KELVIN,
)

COMMAND_BRIGHTNESS = "brightness"
COMMAND_CCT = "cct"
COMMAND_HSI = "hsi"
COMMAND_POWER = "power"

DEFAULT_HS_COLOR = (0.0, 0.0)


@dataclass(frozen=True)
class FixtureCachedState:
    """Optimistic state retained for one fixture."""

    power: bool = False
    brightness: int = 255
    color_temp_kelvin: int = DEFAULT_COLOR_TEMP_KELVIN
    hs_color: tuple[float, float] = DEFAULT_HS_COLOR
    active_color_mode: str = COLOR_MODE_COLOR_TEMP


@dataclass(frozen=True)
class TurnOnPlan:
    """Resolved command and next optimistic state for a HA turn_on call."""

    command: str
    state: FixtureCachedState
    power_on: bool = False


def plan_turn_on(
    state: FixtureCachedState,
    *,
    supports_hs: bool,
    supports_color_temp: bool = True,
    brightness: Any = None,
    kelvin: Any = None,
    hs_color: Any = None,
) -> TurnOnPlan:
    """Resolve one HA turn_on request into a Sidus command preserving mode."""

    requested_brightness = brightness is not None
    requested_kelvin = kelvin is not None and supports_color_temp
    requested_hs = hs_color is not None and supports_hs
    next_brightness = (
        _clamp_brightness(brightness) if requested_brightness else state.brightness
    )
    next_kelvin = _clamp_kelvin(kelvin) if requested_kelvin else state.color_temp_kelvin
    next_hs = _clamp_hs(hs_color) if requested_hs else state.hs_color
    was_off = not state.power

    if requested_hs:
        return TurnOnPlan(
            command=COMMAND_HSI,
            power_on=was_off,
            state=FixtureCachedState(
                power=True,
                brightness=next_brightness,
                color_temp_kelvin=state.color_temp_kelvin,
                hs_color=next_hs,
                active_color_mode=COLOR_MODE_HS,
            ),
        )

    if requested_kelvin:
        return TurnOnPlan(
            command=COMMAND_CCT,
            power_on=was_off,
            state=FixtureCachedState(
                power=True,
                brightness=next_brightness,
                color_temp_kelvin=next_kelvin,
                hs_color=state.hs_color,
                active_color_mode=COLOR_MODE_COLOR_TEMP,
            ),
        )

    if requested_brightness:
        if state.active_color_mode == COLOR_MODE_HS and supports_hs:
            return TurnOnPlan(
                command=COMMAND_HSI,
                power_on=was_off,
                state=FixtureCachedState(
                    power=True,
                    brightness=next_brightness,
                    color_temp_kelvin=state.color_temp_kelvin,
                    hs_color=state.hs_color,
                    active_color_mode=COLOR_MODE_HS,
                ),
            )
        return TurnOnPlan(
            command=COMMAND_CCT if was_off and supports_color_temp else COMMAND_BRIGHTNESS,
            power_on=was_off,
            state=FixtureCachedState(
                power=True,
                brightness=next_brightness,
                color_temp_kelvin=state.color_temp_kelvin,
                hs_color=state.hs_color,
                active_color_mode=(
                    COLOR_MODE_COLOR_TEMP if supports_color_temp else COLOR_MODE_BRIGHTNESS
                ),
            ),
        )

    if was_off:
        if state.active_color_mode == COLOR_MODE_HS and supports_hs:
            return TurnOnPlan(
                command=COMMAND_HSI,
                power_on=True,
                state=FixtureCachedState(
                    power=True,
                    brightness=state.brightness,
                    color_temp_kelvin=state.color_temp_kelvin,
                    hs_color=state.hs_color,
                    active_color_mode=COLOR_MODE_HS,
                ),
            )
        if not supports_color_temp:
            return TurnOnPlan(
                command=COMMAND_BRIGHTNESS,
                power_on=True,
                state=FixtureCachedState(
                    power=True,
                    brightness=state.brightness,
                    color_temp_kelvin=state.color_temp_kelvin,
                    hs_color=state.hs_color,
                    active_color_mode=COLOR_MODE_BRIGHTNESS,
                ),
            )
        return TurnOnPlan(
            command=COMMAND_CCT,
            power_on=True,
            state=FixtureCachedState(
                power=True,
                brightness=state.brightness,
                color_temp_kelvin=state.color_temp_kelvin,
                hs_color=state.hs_color,
                active_color_mode=COLOR_MODE_COLOR_TEMP,
            ),
        )

    return TurnOnPlan(
        command=COMMAND_POWER,
        state=FixtureCachedState(
            power=True,
            brightness=state.brightness,
            color_temp_kelvin=state.color_temp_kelvin,
            hs_color=state.hs_color,
            active_color_mode=state.active_color_mode,
        ),
    )


def turn_off_state(state: FixtureCachedState) -> FixtureCachedState:
    """Power off without wiping cached brightness/color values."""

    return FixtureCachedState(
        power=False,
        brightness=state.brightness,
        color_temp_kelvin=state.color_temp_kelvin,
        hs_color=state.hs_color,
        active_color_mode=state.active_color_mode,
    )


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
