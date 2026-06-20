# Plan 019: Lock the diagnostics key-redaction contract with tests

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 2193a35..HEAD -- custom_components/amaran/diagnostics.py custom_components/amaran/redaction.py custom_components/amaran/client.py`
> If any of those changed since this plan was written, compare the "Current
> state" excerpts below against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (adds tests only — no source change)
- **Depends on**: none
- **Category**: tests (security-adjacent)
- **Planned at**: commit `2193a35`, 2026-06-20

## Why this matters

The integration's entire security promise is that **diagnostics never leak the
Bluetooth Mesh keys**. `README.md:105` ("Diagnostics redact `net_key`, `app_key`,
and pasted JSON fields") and `SECURITY.md` both stake the project's safety on it,
and users are explicitly told it is safe to attach a diagnostics download to a
public issue. That guarantee is implemented entirely in `diagnostics.py` — and
`diagnostics.py` has **zero tests**. Today the redaction is correct (verified by
hand: `redact_sensitive` recurses and `async_redact_data` backstops, and the
`runtime` section copies only key-free scalar fields). So this plan is a
**regression guard**, not a bug fix: it pins the contract so a future refactor
(e.g. someone dumping the whole `client.data` into the runtime section, or
dropping the `redact_sensitive` call) fails CI instead of silently shipping a key
leak.

## Current state

`custom_components/amaran/diagnostics.py` is the only file that assembles the
diagnostics payload. There is no `tests/test_diagnostics.py`.

The entry-redaction path (`diagnostics.py:31-46`):

```python
# diagnostics.py:31-46
async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    stored_clients = hass.data.get(DOMAIN, {}).get(entry.entry_id) or []
    if isinstance(stored_clients, AmaranSidusClient):
        clients = [stored_clients]
    else:
        clients = list(stored_clients)
    return {
        "entry": async_redact_data(redact_sensitive(dict(entry.data)), TO_REDACT),
        "branding": _branding_diagnostics(),
        "model_mapping": _model_mapping_diagnostics(),
        "runtime": [_client_diagnostics(client) for client in clients],
    }
```

- `TO_REDACT = [CONF_APP_KEY, CONF_NET_KEY]` (`diagnostics.py:17`).
- `redact_sensitive` (from `redaction.py:13-25`) recursively replaces any dict key
  in `SENSITIVE_KEYS = {CONF_APP_KEY, CONF_NET_KEY, CONF_IMPORT_JSON}` with the
  string `"**REDACTED**"` (`redaction.py:9-10`). It recurses through nested dicts,
  lists, and tuples — so keys nested inside an entry's `fixtures` / `fixture_catalog`
  list are also redacted.
- `_client_diagnostics(client)` (`diagnostics.py:49-85`) builds the `runtime`
  entry from **named scalar properties only** (`client.name`, `client.model`,
  `client.node_address`, timings, `client.transport_metrics`, cached desired
  state, `client.last_write`, `client.last_command`, …). It does **not** read
  `client.data`, so no key reaches the runtime section. The test must lock that in.

The constants you need (`const.py`): `CONF_NET_KEY = "net_key"`,
`CONF_APP_KEY = "app_key"`, `CONF_FIXTURES = "fixtures"`, `DOMAIN = "amaran"`.

### How tests in this repo stub Home Assistant

There is **no `conftest.py`**. Each test module installs the Home Assistant
modules it needs into `sys.modules` **before** importing the integration (this is
why `tests/*` is exempt from ruff `E402` in `pyproject.toml:5-9`). Two existing
patterns to copy:

- In-memory `Store` and base HA module stubs — `tests/test_client.py:34-63`
  (`_install_homeassistant_stubs`).
- Component/helper stubs (sensor, const, device_registry, entity_registry) —
  `tests/test_sensor.py:12-76` (`_install_sensor_stubs`).

`diagnostics.py` additionally imports
`from homeassistant.components.diagnostics import async_redact_data` — **no
existing test stubs that module**, so you will add a stub for it (Step 1).
`diagnostics.py` also imports `from .client import AmaranSidusClient`, so the full
`test_client.py`-style HA stub set (config_entries, core, helpers, helpers.storage,
helpers.event) must be installed before importing `diagnostics`.

## Commands you will need

Run from the repo root (`/Users/neyako/Documents/hacs-amaran`).

| Purpose | Command | Expected on success |
|---|---|---|
| Full test suite | `python3 -m unittest discover -s tests` | last line `OK`; currently **178** tests |
| This file only | `python3 -m unittest tests.test_diagnostics -v` | `OK` |
| Lint (if installed) | `ruff check custom_components/amaran tests/test_diagnostics.py` | exit 0 — **skip if `ruff` is not installed** |

**Do not use `pytest`** — a shell proxy in this environment intercepts it and
reports "no tests collected". Use `unittest` as above.

## Scope

**In scope** (create only this file):
- `tests/test_diagnostics.py` (create)

**Out of scope** (do NOT touch):
- `custom_components/amaran/diagnostics.py`, `redaction.py`, `client.py`, or any
  other source file. This plan adds tests only. If you believe a source change is
  needed to make a test pass, that is a STOP condition (the redaction is correct
  today; a failing test means the test is wrong).
- `tests/test_fixtures.py` already covers `redact_sensitive` directly — do not
  duplicate or modify it.

## Git workflow

- Branch: `advisor/019-test-diagnostics-redaction`
- Conventional commits, matching `git log` (e.g.
  `test(amaran): lock diagnostics key-redaction contract`).
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Create `tests/test_diagnostics.py` with the HA stub preamble

Mirror the `sys.modules` preamble from `tests/test_client.py:34-63`, and **add**
a stub for `homeassistant.components.diagnostics` whose `async_redact_data`
faithfully reproduces Home Assistant's behaviour (recursively replace any dict
key listed in `to_redact` with a placeholder). A faithful stub — rather than a
pass-through — ensures the test exercises the same redaction layering as
production.

```python
"""Diagnostics key-redaction contract tests."""

from __future__ import annotations

import json
import sys
import types
from typing import Any
import unittest


def _install_homeassistant_stubs() -> None:
    homeassistant = sys.modules.setdefault(
        "homeassistant", types.ModuleType("homeassistant")
    )
    components = sys.modules.setdefault(
        "homeassistant.components", types.ModuleType("homeassistant.components")
    )
    diagnostics = types.ModuleType("homeassistant.components.diagnostics")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = sys.modules.setdefault(
        "homeassistant.helpers", types.ModuleType("homeassistant.helpers")
    )
    storage = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.data: dict[str, Any] | None = None

        async def async_load(self) -> dict[str, Any] | None:
            return self.data

        async def async_save(self, data: dict[str, Any]) -> None:
            self.data = data

    def async_redact_data(data: Any, to_redact: Any) -> Any:
        keys = set(to_redact)

        def _redact(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: "**REDACTED**" if key in keys else _redact(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [_redact(item) for item in value]
            return value

        return _redact(data)

    diagnostics.async_redact_data = async_redact_data
    config_entries.ConfigEntry = object
    core.HomeAssistant = object
    storage.Store = Store

    sys.modules["homeassistant.components.diagnostics"] = diagnostics
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers.storage"] = storage
    sys.modules["homeassistant.helpers.event"] = types.ModuleType(
        "homeassistant.helpers.event"
    )
    homeassistant.components = components
    homeassistant.helpers = helpers


_install_homeassistant_stubs()

from custom_components.amaran.const import (
    CONF_APP_KEY,
    CONF_FIXTURES,
    CONF_NET_KEY,
    DOMAIN,
)
from custom_components.amaran.diagnostics import (
    async_get_config_entry_diagnostics,
)

NET_KEY = "00112233445566778899aabbccddeeff"
APP_KEY = "ffeeddccbbaa99887766554433221100"
```

**Verify**: `python3 -c "import tests.test_diagnostics"` from the repo root →
exit 0, no output (the import-time stubs and integration import succeed).

### Step 2: Add a fake client and the redaction tests

`_client_diagnostics` reads many client properties; build a `types.SimpleNamespace`
with the attributes it touches (`diagnostics.py:49-85`). Critically, give the fake
client a `data` dict that **contains the raw keys**, even though
`_client_diagnostics` does not read it today — that way the "keys never appear in
the output" assertion would catch any future change that starts dumping
`client.data` into the runtime section.

```python
def _fake_client() -> types.SimpleNamespace:
    """A client whose runtime diagnostics must never expose mesh keys."""

    return types.SimpleNamespace(
        name="Ace",
        model="Ace 25c",
        node_address=0x000B,
        source_address=0x000F,
        supported_color_modes=("color_temp", "hs"),
        sequence=100001,
        connected=True,
        transport_state="proxy_ready",
        last_connect_time=1.0,
        last_write_latency_ms=12.5,
        transport_mode="persistent",
        proxy_selection="auto",
        proxy_address="",
        fixture_reachable=True,
        fixture_stale_seconds=None,
        presence_checking_enabled=False,
        presence_unavailable_after=120.0,
        last_advertisement_seen=None,
        last_advertisement_address=None,
        last_advertisement_rssi=None,
        last_proxy_advertisement_seen=None,
        desired_power=True,
        desired_brightness=200,
        desired_color_temp_kelvin=5000,
        desired_hs_color=None,
        desired_active_color_mode="color_temp",
        last_bluetooth_device=None,
        last_write=None,
        last_command=None,
        last_physical_validation=None,
        # Present on the real client; must NOT reach diagnostics output.
        transport_metrics={"state": "proxy_ready", "last_write_time": None},
        data={CONF_NET_KEY: NET_KEY, CONF_APP_KEY: APP_KEY},
    )


class DiagnosticsRedactionTest(unittest.IsolatedAsyncioTestCase):
    def _entry(self) -> types.SimpleNamespace:
        # Keys at top level AND nested inside a fixtures list (both must redact).
        return types.SimpleNamespace(
            entry_id="entry-1",
            data={
                "name": "Ace",
                CONF_NET_KEY: NET_KEY,
                CONF_APP_KEY: APP_KEY,
                CONF_FIXTURES: [
                    {"name": "Ace", CONF_NET_KEY: NET_KEY, CONF_APP_KEY: APP_KEY}
                ],
            },
        )

    async def test_entry_section_redacts_top_level_and_nested_keys(self) -> None:
        hass = types.SimpleNamespace(data={DOMAIN: {"entry-1": [_fake_client()]}})
        result = await async_get_config_entry_diagnostics(hass, self._entry())

        entry = result["entry"]
        self.assertEqual(entry[CONF_NET_KEY], "**REDACTED**")
        self.assertEqual(entry[CONF_APP_KEY], "**REDACTED**")
        nested = entry[CONF_FIXTURES][0]
        self.assertEqual(nested[CONF_NET_KEY], "**REDACTED**")
        self.assertEqual(nested[CONF_APP_KEY], "**REDACTED**")

    async def test_raw_keys_never_appear_anywhere_in_output(self) -> None:
        hass = types.SimpleNamespace(data={DOMAIN: {"entry-1": [_fake_client()]}})
        result = await async_get_config_entry_diagnostics(hass, self._entry())

        serialized = json.dumps(result)
        self.assertNotIn(NET_KEY, serialized)
        self.assertNotIn(APP_KEY, serialized)

    async def test_runtime_section_present_and_key_free(self) -> None:
        hass = types.SimpleNamespace(data={DOMAIN: {"entry-1": [_fake_client()]}})
        result = await async_get_config_entry_diagnostics(hass, self._entry())

        self.assertEqual(len(result["runtime"]), 1)
        self.assertEqual(result["runtime"][0]["name"], "Ace")
        self.assertNotIn(NET_KEY, json.dumps(result["runtime"]))
        self.assertNotIn(APP_KEY, json.dumps(result["runtime"]))


if __name__ == "__main__":
    unittest.main()
```

If `json.dumps(result)` raises because `_model_mapping_diagnostics()` or
`_branding_diagnostics()` returns a non-serializable value, that is unexpected —
those return plain dicts/strings of the bundled `product.json` and brand paths. If
it happens, it is a STOP condition (a real serialization bug worth reporting), not
something to paper over by trimming the assertion.

**Verify**: `python3 -m unittest tests.test_diagnostics -v` → `OK`, 3 tests.

### Step 3: Confirm the whole suite still passes

**Verify**: `python3 -m unittest discover -s tests` → last line `OK`, **181**
tests (178 existing + 3 new).

## Test plan

- New file `tests/test_diagnostics.py`, class `DiagnosticsRedactionTest`:
  - `test_entry_section_redacts_top_level_and_nested_keys` — net/app keys are
    `**REDACTED**` both at the top level and inside the nested `fixtures` list.
  - `test_raw_keys_never_appear_anywhere_in_output` — the raw key hex strings
    appear nowhere in `json.dumps(result)` (covers entry + runtime + every
    section). This is the core regression guard.
  - `test_runtime_section_present_and_key_free` — runtime diagnostics are produced
    and contain no key, even though the fake client carries keys in `.data`.
- Structural pattern to follow: `tests/test_client.py` (HA `sys.modules` stub +
  in-memory `Store`) and `tests/test_sensor.py` (component stubs, `SimpleNamespace`
  fakes).
- Verification: `python3 -m unittest discover -s tests` → `OK`, 181 tests.

## Done criteria

ALL must hold:

- [ ] `tests/test_diagnostics.py` exists.
- [ ] `python3 -m unittest tests.test_diagnostics -v` → `OK`, 3 tests.
- [ ] `python3 -m unittest discover -s tests` exits 0, last line `OK`, **181** total.
- [ ] `git status --porcelain` lists only `tests/test_diagnostics.py` (and, if you
      committed, no other file). No source file under `custom_components/` changed.
- [ ] `plans/README.md` status row for 019 updated.

## STOP conditions

Stop and report (do not improvise) if:

- The "Current state" excerpts do not match the live `diagnostics.py` /
  `redaction.py` (drift since `2193a35`).
- A redaction test **fails** — that would mean keys actually leak (a real
  vulnerability) or `_client_diagnostics` now reads `client.data`. Report it; do
  not weaken the assertion to make it pass.
- `json.dumps(result)` raises (a real serialization bug in a diagnostics helper).
- Making a test pass appears to require editing any file under
  `custom_components/amaran/`.

## Maintenance notes

- These tests are the safety net for the project's headline security claim. A
  reviewer should treat any future change to `diagnostics.py` or `redaction.py`
  that makes them fail as a release blocker until the redaction is restored.
- If a new sensitive field is ever stored in `entry.data` (e.g. a device key),
  add its `CONF_*` constant to `SENSITIVE_KEYS` in `redaction.py` **and** extend
  `test_raw_keys_never_appear_anywhere_in_output` with that field — the test is
  the checklist.
- If `_client_diagnostics` is ever intentionally extended to surface more runtime
  data, keep it to named non-secret fields; never dump `client.data` wholesale —
  the third test will catch it if you forget.
