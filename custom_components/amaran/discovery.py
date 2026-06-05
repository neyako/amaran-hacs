"""Bluetooth discovery policy helpers."""

from __future__ import annotations

from typing import Any


def bluetooth_discovery_enabled(hass: Any) -> bool:
    """Return false because Bluetooth discovery is intentionally disabled."""

    return False
