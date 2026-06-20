"""Persistent light-state store key and round-trip tests."""

from __future__ import annotations

from hashlib import sha1
import sys
import types
from typing import Any
import unittest


def _install_homeassistant_stubs() -> None:
    homeassistant = sys.modules.setdefault(
        "homeassistant", types.ModuleType("homeassistant")
    )
    helpers = sys.modules.setdefault(
        "homeassistant.helpers", types.ModuleType("homeassistant.helpers")
    )
    storage = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        def __init__(
            self, hass: Any, version: int, key: str, *a: Any, **k: Any
        ) -> None:
            self.hass = hass
            self.version = version
            self.key = key
            self.data: dict[str, Any] | None = None

        async def async_load(self) -> dict[str, Any] | None:
            return self.data

        async def async_save(self, data: dict[str, Any]) -> None:
            self.data = data

    storage.Store = Store
    sys.modules["homeassistant.helpers.storage"] = storage
    homeassistant.helpers = helpers


_install_homeassistant_stubs()

import custom_components.amaran.state_store as state_store_module
from custom_components.amaran.const import CONF_BLE_MAC, CONF_NODE_ADDRESS
from custom_components.amaran.state import FixtureCachedState
from custom_components.amaran.state_store import (
    AmaranLightStateStore,
    _state_store_key,
)

# Belt-and-suspenders: if state_store was imported before the stub above (e.g. by
# another test in the same process), rebind its Store reference to the in-memory
# stub so these tests never touch real disk.
def _reset_state_store_stub() -> None:
    _install_homeassistant_stubs()
    state_store_module.Store = sys.modules["homeassistant.helpers.storage"].Store


_reset_state_store_stub()


def _client(
    *, mac: str = "AA:BB:CC:DD:EE:01", node: int = 0x000B, src: int = 0x000F
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        data={CONF_BLE_MAC: mac, CONF_NODE_ADDRESS: node},
        node_address=node,
        source_address=src,
    )


class StateStoreKeyTest(unittest.TestCase):
    def test_key_matches_documented_formula(self) -> None:
        client = _client(mac="AA:BB:CC:DD:EE:01", node=0x000B, src=0x000F)
        identity = "aa_bb_cc_dd_ee_01:000b:000f"
        expected = (
            f"amaran_light_state_{sha1(identity.encode('utf-8')).hexdigest()[:16]}"
        )
        self.assertEqual(_state_store_key(client), expected)

    def test_key_is_stable_for_same_inputs(self) -> None:
        a = _state_store_key(_client())
        b = _state_store_key(_client())
        self.assertEqual(a, b)

    def test_key_differs_when_node_or_source_or_mac_differs(self) -> None:
        base = _state_store_key(_client())
        self.assertNotEqual(base, _state_store_key(_client(node=0x000C)))
        self.assertNotEqual(base, _state_store_key(_client(src=0x0010)))
        self.assertNotEqual(base, _state_store_key(_client(mac="AA:BB:CC:DD:EE:02")))

    def test_key_has_expected_prefix_and_digest_length(self) -> None:
        key = _state_store_key(_client())
        self.assertTrue(key.startswith("amaran_light_state_"))
        digest = key.removeprefix("amaran_light_state_")
        self.assertEqual(len(digest), 16)
        self.assertTrue(all(char in "0123456789abcdef" for char in digest))


class StateStoreRoundTripTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        _reset_state_store_stub()

    async def test_save_then_load_preserves_state_fields(self) -> None:
        store = AmaranLightStateStore(hass=object(), client=_client())
        state = FixtureCachedState(
            power=True,
            brightness=200,
            color_temp_kelvin=5000,
            hs_color=(120.0, 80.0),
            active_color_mode="hs",
        )
        await store.async_save(state, assumed_state=False)
        loaded = await store.async_load()

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["power"], True)
        self.assertEqual(loaded["brightness"], 200)
        self.assertEqual(loaded["color_temp_kelvin"], 5000)
        self.assertEqual(loaded["hs_color"], [120.0, 80.0])
        self.assertEqual(loaded["color_mode"], "hs")
        self.assertEqual(loaded["assumed_state"], False)
        self.assertIn("last_updated", loaded)

    async def test_load_returns_none_when_store_empty(self) -> None:
        store = AmaranLightStateStore(hass=object(), client=_client())
        self.assertIsNone(await store.async_load())

    async def test_load_ignores_non_dict_payload(self) -> None:
        store = AmaranLightStateStore(hass=object(), client=_client())
        store._store.data = ["not", "a", "dict"]  # type: ignore[assignment]
        self.assertIsNone(await store.async_load())
