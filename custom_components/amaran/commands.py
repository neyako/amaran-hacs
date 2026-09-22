"""Sidus command planning for Amaran light state changes."""

from __future__ import annotations

from .protocol import (
    brightness_payload_ha,
    cct_payload_ha,
    hsi_payload_ha,
    rgb_payload_ha,
    power_payload,
    power_status_request_payload,
    status_request_payload,
)


def brightness_payloads(*, brightness: int, power_on: bool = False) -> list[bytes]:
    """Build brightness-only payloads, optionally waking the light first."""

    payload = brightness_payload_ha(brightness)
    if power_on:
        return [power_payload(True), payload]
    return [payload]


def brightness_cct_payload(*, brightness: int, kelvin: int, gm: int = 0) -> bytes:
    """Build the CCT payload that carries both brightness and CCT."""

    return cct_payload_ha(brightness=brightness, kelvin=kelvin, gm=gm)


def cct_payloads(
    *, brightness: int, kelvin: int, power_on: bool = False, gm: int = 0
) -> list[bytes]:
    """Build CCT payloads, optionally waking the light first."""

    payload = brightness_cct_payload(brightness=brightness, kelvin=kelvin, gm=gm)
    if power_on:
        return [power_payload(True), payload]
    return [payload]


def hsi_payloads(
    *,
    brightness: int,
    hue: int | float,
    saturation: int | float,
    power_on: bool = False,
) -> list[bytes]:
    """Build HSI payloads, optionally waking the light first."""

    payload = hsi_payload_ha(
        brightness=brightness,
        hue=hue,
        saturation=saturation,
    )
    if power_on:
        return [power_payload(True), payload]
    return [payload]


def brightness_cct_payloads(
    *, brightness: int, kelvin: int, power_on: bool = False, gm: int = 0
) -> list[bytes]:
    """Compatibility wrapper for callers that set brightness and CCT together."""

    return cct_payloads(
        brightness=brightness,
        kelvin=kelvin,
        power_on=power_on,
        gm=gm,
    )


def rgb_payloads(
    *, brightness: int, rgb_color: tuple[int, int, int], power_on: bool = False
) -> list[bytes]:
    """Build native RGB payloads, optionally waking the light first."""

    payload = rgb_payload_ha(brightness=brightness, rgb_color=rgb_color)
    return [power_payload(True), payload] if power_on else [payload]


def power_on_payloads() -> list[bytes]:
    """Build power-on payloads without changing brightness or CCT."""

    return [power_payload(True)]


def power_off_payloads() -> list[bytes]:
    """Build power-off payloads."""

    return [power_payload(False)]


def status_request_payloads() -> list[bytes]:
    """Build a harmless status request payload."""

    return [status_request_payload()]


def power_status_request_payloads() -> list[bytes]:
    """Build the Sidus power/battery status request payload."""

    return [power_status_request_payload()]
