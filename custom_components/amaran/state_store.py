"""Persistent per-light state cache."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha1
import time
from typing import Any

from homeassistant.helpers.storage import Store

from .const import CONF_NODE_ADDRESS, DOMAIN
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
                "rgb_color": list(state.rgb_color),
                "effect": state.effect,
                "color_mode": state.active_color_mode,
                "last_updated": time.time(),
                "assumed_state": assumed_state,
            }
        )


async def async_move_light_state(
    hass: Any, data: Mapping[str, Any], old_source: int, new_source: int
) -> None:
    """Carry a light's cached state over to a new source address."""

    node = int(data[CONF_NODE_ADDRESS])
    old_store = Store(hass, _STORE_VERSION, _key(data, node, old_source))
    if (state := await old_store.async_load()) is None:
        return
    await Store(hass, _STORE_VERSION, _key(data, node, new_source)).async_save(state)
    await old_store.async_remove()


def _state_store_key(client: Any) -> str:
    return _key(client.data, int(client.node_address), int(client.source_address))


def _key(data: Mapping[str, Any], node_address: int, source_address: int) -> str:
    identity = (
        f"{fixture_unique_id(dict(data))}:{node_address:04x}:{source_address:04x}"
    )
    digest = sha1(identity.encode("utf-8")).hexdigest()[:16]
    return f"{DOMAIN}_light_state_{digest}"
