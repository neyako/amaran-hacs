"""Pure optimistic light state planning."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .const import (
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_HS,
    COLOR_MODE_RGB,
    DEFAULT_COLOR_TEMP_KELVIN,
    MAX_COLOR_TEMP_KELVIN,
    MIN_COLOR_TEMP_KELVIN,
)

COMMAND_BRIGHTNESS = "brightness"
COMMAND_CCT = "cct"
COMMAND_HSI = "hsi"
COMMAND_RGB = "rgb"
COMMAND_EFFECT = "effect"
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
    rgb_color: tuple[int, int, int] = (255, 255, 255)
    effect: str | None = None


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
    supports_rgb: bool = False,
    brightness: Any = None,
    kelvin: Any = None,
    hs_color: Any = None,
    rgb_color: Any = None,
    effect: str | None = None,
    minimum_kelvin: int = MIN_COLOR_TEMP_KELVIN,
    maximum_kelvin: int = MAX_COLOR_TEMP_KELVIN,
) -> TurnOnPlan:
    """Resolve one HA turn_on request into a Sidus command preserving mode."""

    was_off = not state.power
    next_state = replace(
        state, power=True,
        brightness=_clamp_brightness(brightness) if brightness is not None else state.brightness,
    )
    if effect is not None and effect != "off":
        return TurnOnPlan(COMMAND_EFFECT, replace(next_state, effect=effect), was_off)
    if effect == "off":
        next_state = replace(next_state, effect=None)
    if rgb_color is not None and supports_rgb:
        return TurnOnPlan(COMMAND_RGB, replace(
            next_state, rgb_color=clamp_rgb(rgb_color), active_color_mode=COLOR_MODE_RGB, effect=None,
        ), was_off)
    if hs_color is not None and supports_hs:
        return TurnOnPlan(COMMAND_HSI, replace(
            next_state, hs_color=_clamp_hs(hs_color), active_color_mode=COLOR_MODE_HS, effect=None,
        ), was_off)
    if kelvin is not None and supports_color_temp:
        return TurnOnPlan(COMMAND_CCT, replace(
            next_state,
            color_temp_kelvin=clamp_kelvin(kelvin, minimum_kelvin, maximum_kelvin),
            active_color_mode=COLOR_MODE_COLOR_TEMP,
            effect=None,
        ), was_off)
    if next_state.effect is not None and (brightness is not None or was_off):
        return TurnOnPlan(COMMAND_EFFECT, next_state, was_off)
    if brightness is not None or was_off or effect == "off":
        if state.active_color_mode == COLOR_MODE_RGB and supports_rgb:
            return TurnOnPlan(COMMAND_RGB, next_state, was_off)
        if state.active_color_mode == COLOR_MODE_HS and supports_hs:
            return TurnOnPlan(COMMAND_HSI, next_state, was_off)
        return TurnOnPlan(
            COMMAND_CCT if (was_off or effect == "off") and supports_color_temp else COMMAND_BRIGHTNESS,
            replace(next_state, active_color_mode=(
                COLOR_MODE_COLOR_TEMP if supports_color_temp else COLOR_MODE_BRIGHTNESS
            )),
            was_off,
        )
    return TurnOnPlan(COMMAND_POWER, next_state)


def turn_off_state(state: FixtureCachedState) -> FixtureCachedState:
    """Power off without wiping cached brightness/color values."""

    return replace(state, power=False)


def clamp_rgb(rgb_color: Any) -> tuple[int, int, int]:
    """Normalize HA channels, requiring exactly three values."""

    red, green, blue = rgb_color
    return tuple(max(0, min(255, int(channel))) for channel in (red, green, blue))


def _clamp_brightness(brightness: Any) -> int:
    return max(0, min(255, int(brightness)))


def clamp_kelvin(kelvin: Any, minimum: int, maximum: int) -> int:
    """Clamp a requested or restored temperature to the model's supported range."""

    return max(minimum, min(maximum, int(kelvin)))


def _clamp_hs(hs_color: Any) -> tuple[float, float]:
    hue, saturation = hs_color
    return (
        max(0.0, min(360.0, float(hue))),
        max(0.0, min(100.0, float(saturation))),
    )
