"""Persistent per-light state cache."""

from __future__ import annotations

from hashlib import sha1
import time
from typing import Any

from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .fixtures import fixture_unique_id
from .state import FixtureCachedState

_STORE_VERSION = 1


class AmaranLightStateStore:
    """Store last HA-known light state without sending startup commands."""

    def __init__(self, hass: Any, client: Any) -> None:
        key = _state_store_key(client)
        self._store = Store(hass, _STORE_VERSION, key)

    async def async_load(self) -> dict[str, Any] | None:
        """Load cached state."""

        data = await self._store.async_load()
        return data if isinstance(data, dict) else None

    async def async_save(
        self, state: FixtureCachedState, *, assumed_state: bool
    ) -> None:
        """Save cached state."""

        await self._store.async_save(
            {
                "power": state.power,
                "brightness": state.brightness,
                "color_temp_kelvin": state.color_temp_kelvin,
                "hs_color": list(state.hs_color),
                "color_mode": state.active_color_mode,
                "last_updated": time.time(),
                "assumed_state": assumed_state,
            }
        )


def _state_store_key(client: Any) -> str:
    identity = (
        f"{fixture_unique_id(client.data)}:"
        f"{int(client.node_address):04x}:"
        f"{int(client.source_address):04x}"
    )
    digest = sha1(identity.encode("utf-8")).hexdigest()[:16]
    return f"{DOMAIN}_light_state_{digest}"
