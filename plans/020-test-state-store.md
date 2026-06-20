# Plan 020: Pin the persisted light-state store key and round-trip with tests

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 2193a35..HEAD -- custom_components/amaran/state_store.py custom_components/amaran/fixtures.py custom_components/amaran/state.py`
> If any of those changed since this plan was written, compare the "Current
> state" excerpts below against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (adds tests only — no source change)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `2193a35`, 2026-06-20

## Why this matters

`AmaranLightStateStore` persists each light's last optimistic state (power,
brightness, CCT, HS, mode) so that after a Home Assistant restart the light is
restored **without sending any command** (the AGENTS.md "State Restoration" rule:
restore previous state, mark it assumed, never force 100%/5600K/turn-on). The
identity of that persisted blob is the storage **key** derived in
`_state_store_key` from the fixture's unique id + node address + source address.
The whole module has **zero tests**. Two silent-failure modes are unguarded:

1. **Key drift** — if anyone changes `_state_store_key` (or the `fixture_unique_id`
   it depends on), every existing light's persisted state is orphaned: on the next
   restart the store loads `None`, the light falls back to the defaults (255
   brightness / 5600 K), and the user sees their lights "reset" with no error.
2. **Round-trip shape drift** — if `async_save` and the reader in
   `light.py:_restore_from_persistent_state` disagree on the dict keys, restore
   silently no-ops.

This plan adds a characterization test that pins the key format and a round-trip
test that pins the saved shape, so either drift fails CI instead of users.

## Current state

`custom_components/amaran/state_store.py` (the whole file, 56 lines):

```python
# state_store.py:18-56
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
```

Facts the tests rely on:

- `Store` is `from homeassistant.helpers.storage import Store` (`state_store.py:9`),
  `_STORE_VERSION = 1` (`state_store.py:15`), `DOMAIN = "amaran"` (`const.py:3`).
- `fixture_unique_id(data)` (`fixtures.py:197-210`) returns, for data containing
  `CONF_BLE_MAC`, `_normalize_identifier(str(mac))` where `_normalize_identifier`
  (`fixtures.py:583-584`) is
  `re.sub(r"[^0-9a-zA-Z]+", "_", value.strip().lower()).strip("_")`. So
  `"AA:BB:CC:DD:EE:01"` → `"aa_bb_cc_dd_ee_01"`.
- The reader in `light.py:365-375` (`_restore_from_persistent_state`) consumes the
  keys `power`, `brightness`, `color_temp_kelvin`, `hs_color`, `color_mode`,
  `assumed_state` — the save shape must keep all of them.
- `FixtureCachedState` is `from .state import FixtureCachedState`
  (`state.py:25-33`), a frozen dataclass with defaults
  `power=False, brightness=255, color_temp_kelvin=DEFAULT_COLOR_TEMP_KELVIN (5600),
  hs_color=(0.0, 0.0), active_color_mode="color_temp"`.

### How tests in this repo stub Home Assistant

No `conftest.py`. Each test installs the HA modules it needs into `sys.modules`
**before** importing the integration (the `tests/*` ruff `E402` exemption,
`pyproject.toml:5-9`). For an in-memory `Store`, copy
`tests/test_client.py:34-63` (`_install_homeassistant_stubs`). Importing
`state_store` only requires `homeassistant.helpers.storage.Store` to be stubbed
(its other imports — `.fixtures`, `.state`, `.const` — pull no Home Assistant
modules; `.fixtures` → `.protocol` uses the real `cryptography`, already a CI test
dependency).

## Commands you will need

Run from the repo root (`/Users/neyako/Documents/hacs-amaran`).

| Purpose | Command | Expected on success |
|---|---|---|
| Full test suite | `python3 -m unittest discover -s tests` | last line `OK`; currently **178** tests |
| This file only | `python3 -m unittest tests.test_state_store -v` | `OK` |
| Lint (if installed) | `ruff check tests/test_state_store.py` | exit 0 — **skip if `ruff` is not installed** |

**Do not use `pytest`** — a shell proxy intercepts it and reports "no tests
collected". Use `unittest`.

## Scope

**In scope** (create only this file):
- `tests/test_state_store.py` (create)

**Out of scope** (do NOT touch):
- `custom_components/amaran/state_store.py` and every other source file. This plan
  adds tests only. If a test seems to require a source change, STOP and report.

## Git workflow

- Branch: `advisor/020-test-state-store`
- Conventional commits, matching `git log` (e.g.
  `test(amaran): pin light-state store key and round-trip`).
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Create `tests/test_state_store.py` with the HA `Store` stub

```python
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
        def __init__(self, hass: Any, version: int, key: str, *a: Any, **k: Any) -> None:
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
from custom_components.amaran.state_store import (
    AmaranLightStateStore,
    _state_store_key,
)
from custom_components.amaran.state import FixtureCachedState
from custom_components.amaran.const import CONF_BLE_MAC, CONF_NODE_ADDRESS

# Belt-and-suspenders: if state_store was imported before the stub above (e.g. by
# another test in the same process), rebind its Store reference to the in-memory
# stub so these tests never touch real disk.
state_store_module.Store = sys.modules["homeassistant.helpers.storage"].Store


def _client(
    *, mac: str = "AA:BB:CC:DD:EE:01", node: int = 0x000B, src: int = 0x000F
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        data={CONF_BLE_MAC: mac, CONF_NODE_ADDRESS: node},
        node_address=node,
        source_address=src,
    )
```

**Verify**: `python3 -c "import tests.test_state_store"` from the repo root →
exit 0, no output.

### Step 2: Add the key-stability characterization test

Recompute the expected key **independently** in the test using the documented
formula, so any change to `_state_store_key`'s identity string or hash fails here.

```python
class StateStoreKeyTest(unittest.TestCase):
    def test_key_matches_documented_formula(self) -> None:
        client = _client(mac="AA:BB:CC:DD:EE:01", node=0x000B, src=0x000F)
        # Independent recomputation of the contract (do NOT call the source helper
        # to build the expectation — that would make the test circular).
        identity = "aa_bb_cc_dd_ee_01:000b:000f"
        expected = f"amaran_light_state_{sha1(identity.encode('utf-8')).hexdigest()[:16]}"
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
```

**Verify**: `python3 -m unittest tests.test_state_store.StateStoreKeyTest -v` →
`OK`, 4 tests. If `test_key_matches_documented_formula` fails, the identity string
in the test must equal `fixture_unique_id({CONF_BLE_MAC: "AA:BB:CC:DD:EE:01"}) +
":000b:000f"`; print `_state_store_key(_client())` and reconcile the identity
string — but do **not** change `state_store.py` to match the test.

### Step 3: Add the save/load round-trip test

```python
class StateStoreRoundTripTest(unittest.IsolatedAsyncioTestCase):
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
        self.assertEqual(loaded["hs_color"], [120.0, 80.0])  # saved as a list
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
```

The saved-shape assertions deliberately match the keys read by
`light.py:_restore_from_persistent_state` (`power`, `brightness`,
`color_temp_kelvin`, `hs_color`, `color_mode`, `assumed_state`). If the save shape
ever drops one, this test fails — which is the intended guard.

**Verify**: `python3 -m unittest tests.test_state_store -v` → `OK`, 7 tests total.

### Step 4: Confirm the whole suite still passes

**Verify**: `python3 -m unittest discover -s tests` → last line `OK`, **185**
tests (178 existing + 7 new).

## Test plan

- New file `tests/test_state_store.py`:
  - `StateStoreKeyTest` (4 tests) — key matches the documented sha1 formula, is
    stable across calls, changes when node/source/MAC change, and has the expected
    `amaran_light_state_<16 hex>` shape.
  - `StateStoreRoundTripTest` (3 tests) — save→load preserves every field the
    light reader consumes (incl. `hs_color` saved as a list); empty store loads
    `None`; a non-dict payload loads `None`.
- Structural pattern to follow: `tests/test_client.py` for the in-memory `Store`
  stub; `tests/test_state.py` for plain `unittest.TestCase` assertions.
- Verification: `python3 -m unittest discover -s tests` → `OK`, 185 tests.

## Done criteria

ALL must hold:

- [ ] `tests/test_state_store.py` exists.
- [ ] `python3 -m unittest tests.test_state_store -v` → `OK`, 7 tests.
- [ ] `python3 -m unittest discover -s tests` exits 0, last line `OK`, **185** total.
- [ ] `git status --porcelain` lists only `tests/test_state_store.py`; no source
      file under `custom_components/` changed.
- [ ] `plans/README.md` status row for 020 updated.

## STOP conditions

Stop and report (do not improvise) if:

- The "Current state" excerpts do not match the live `state_store.py` /
  `fixtures.py` (drift since `2193a35`).
- `test_key_matches_documented_formula` fails because the live identity format
  differs from the excerpt above — report the actual `_state_store_key(_client())`
  value; do not edit `state_store.py`.
- Any test would require importing real Home Assistant or writing to disk — the
  in-memory `Store` stub must be in place before the integration import.

## Maintenance notes

- `_state_store_key` is an **identity** function: changing it orphans every user's
  persisted light state on upgrade. If it ever must change, that is a storage
  migration, not a refactor — `test_key_matches_documented_formula` is the tripwire
  that forces the conversation.
- The round-trip test's asserted keys mirror `light.py:_restore_from_persistent_state`.
  If you add a field to the saved state, read it back on restore **and** extend the
  round-trip assertions together.
