# Plan 012: Expose green/magenta (G/M) tint for CCT lights as a number entity

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 49d7685..HEAD -- custom_components/amaran/protocol.py custom_components/amaran/commands.py custom_components/amaran/client.py custom_components/amaran/__init__.py`
> If any of those files changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (touches the working CCT command path and adds a platform)
- **Depends on**: none
- **Category**: direction (feature)
- **Planned at**: commit `49d7685`, 2026-06-20

## Why this matters

Amaran/Sidus lights have a green↔magenta (G/M) point that color-matches a light
to other fixtures — a signature pro feature. The protocol layer **already packs
it**: `protocol.cct_payload(..., gm=N)` encodes the −10..+10 reference offset
(`custom_components/amaran/protocol.py:138-186`). But every caller hardcodes
`gm=0`, so the control is dead one layer below the surface. This plan threads the
existing `gm` value through the command and client layers and exposes it as a
per-light **number** entity (Home Assistant's `light` platform has no native G/M
field). Net effect: a "Green / magenta" slider per CCT-capable light that
actually shifts the tint.

Scope is **CCT mode only**. The HSI setter deliberately leaves its optional
CCT/G·M fields zero (`docs/protocol.md:116`), so HSI-mode G/M is out of scope and
left for a future plan.

## Current state

Files and their roles:

- `custom_components/amaran/protocol.py` — byte packing. `cct_payload` /
  `cct_payload_percent` / `cct_payload_ha` already accept `gm` and pack it.
  **No change needed here.** Confirm the signature still reads:
  ```python
  # protocol.py:179
  def cct_payload_ha(*, brightness: int, kelvin: int, gm: int = 0) -> bytes:
  ```
- `custom_components/amaran/commands.py` — payload list builders. `cct_payloads`
  and `brightness_cct_payload` drop `gm`:
  ```python
  # commands.py:24
  def brightness_cct_payload(*, brightness: int, kelvin: int) -> bytes:
      """Build the CCT payload that carries both brightness and CCT."""
      return cct_payload_ha(brightness=brightness, kelvin=kelvin)

  # commands.py:30
  def cct_payloads(
      *, brightness: int, kelvin: int, power_on: bool = False
  ) -> list[bytes]:
      payload = brightness_cct_payload(brightness=brightness, kelvin=kelvin)
      if power_on:
          return [power_payload(True), payload]
      return [payload]

  # commands.py:60
  def brightness_cct_payloads(
      *, brightness: int, kelvin: int, power_on: bool = False
  ) -> list[bytes]:
      return cct_payloads(brightness=brightness, kelvin=kelvin, power_on=power_on)
  ```
- `custom_components/amaran/client.py` — per-light client. Holds desired state and
  builds CCT sends:
  ```python
  # client.py:536-540  (desired-state fields, in __init__)
          self._desired_power: bool | None = None
          self._desired_brightness: int | None = None
          self._desired_color_temp_kelvin: int | None = None
          self._desired_hs_color: tuple[float, float] | None = None
          self._desired_active_color_mode: str = COLOR_MODE_COLOR_TEMP

  # client.py:692-695
      @property
      def supports_color_temp(self) -> bool:
          """Return true when this fixture supports CCT commands."""
          return COLOR_MODE_COLOR_TEMP in self._supported_color_modes

  # client.py:1041-1073  (the CCT send path)
      async def async_set_brightness_cct(
          self, *, brightness: int, kelvin: int, power_on: bool = False
      ) -> None:
          brightness = _clamp_brightness(brightness)
          kelvin = _clamp_kelvin(kelvin)
          sidus_intensity = round(brightness / 255 * 1000)
          payload = brightness_cct_payload(brightness=brightness, kelvin=kelvin)
          _LOGGER.debug(...)
          await self.async_send_siduses(
              cct_payloads(
                  brightness=brightness,
                  kelvin=kelvin,
                  power_on=power_on,
              ),
              first_payload_delay=_POWER_SETTLE_DELAY if power_on else 0.0,
          )
          self._desired_power = True
          self._desired_brightness = brightness
          self._desired_color_temp_kelvin = kelvin
          self._desired_active_color_mode = COLOR_MODE_COLOR_TEMP
  ```
  Module-level clamp helpers live near the bottom of `client.py` (e.g.
  `_clamp_brightness`, `_clamp_kelvin`, `_clamp_hs`). Add the new clamp beside
  them.
- `custom_components/amaran/__init__.py` — platform wiring. The platform tuple
  appears **twice**, identically:
  ```python
  # __init__.py:194 (in async_setup_entry)
      platforms = (Platform.LIGHT, Platform.SENSOR)
  # __init__.py:306 (in async_unload_entry)
      platforms = (Platform.LIGHT, Platform.SENSOR)
  ```
- `custom_components/amaran/sensor.py` — **the platform exemplar**. Copy its
  structure for the new `number.py`: module docstring, `async_setup_entry`
  pulling `clients = hass.data[DOMAIN][entry.entry_id]`, an entity class with
  `_attr_has_entity_name = True` and a literal `_attr_name` (see
  `sensor.py:49-50` `_attr_name = "Transport"` and `sensor.py:122-123`
  `_attr_name = "Battery"` — both use a direct string, **not** a translation
  key, and pass CI hassfest), a `device_info` property, and a stable
  `_attr_unique_id`. Match the unique-id shape used by the light:
  ```python
  # light.py:78-81
          self._attr_unique_id = (
              f"{client.ble_mac or client.address}_node_{client.node_address}_"
              f"src_{client.source_address}"
          )
  ```

Conventions to honor (from `AGENTS.md`):
- User-facing text says "light", never "fixture/proxy/transport/mesh".
- Never send a command during HA startup; never turn a light on unexpectedly.
- Parity-locked protocol packing must not be renamed without parity tests
  (you are not renaming anything — only adding a pass-through `gm` argument).

## Commands you will need

Run from the repo root (`/Users/neyako/Documents/hacs-amaran`).

| Purpose | Command | Expected on success |
|---|---|---|
| Full test suite | `python3 -m unittest discover -s tests` | last line `OK` (no `FAILED`) |
| One module | `python3 -m unittest tests.test_number -v` | `OK` |
| Protocol tests | `python3 -m unittest tests.test_protocol -v` | `OK` |
| Lint (non-blocking) | `ruff check custom_components/amaran` | exit 0 — **skip if `ruff` is not installed** |

**Do not use `pytest`** — a shell proxy in this environment intercepts it and
reports "no tests collected". Use `unittest` as above.

## Scope

**In scope** (modify only these):
- `custom_components/amaran/commands.py`
- `custom_components/amaran/client.py`
- `custom_components/amaran/number.py` (create)
- `custom_components/amaran/__init__.py` (the two platform tuples only)
- `tests/test_protocol.py` (add G/M packing assertions)
- `tests/test_client.py` (add client G/M threading tests)
- `tests/test_number.py` (create — entity test)

**Out of scope** (do NOT touch):
- `custom_components/amaran/protocol.py` — `gm` is already implemented; do not
  re-pack or "improve" it. Renaming any packing symbol breaks parity tests.
- `custom_components/amaran/light.py` and `state.py` — the light's turn_on plan
  stays untouched. G/M is a side-channel control, not part of `plan_turn_on`.
- The HSI path (`async_set_hsi`, `hsi_payload*`). HSI-mode G/M is explicitly
  deferred.
- `strings.json` / `translations/en.json` — the number entity uses a literal
  `_attr_name`, so no translation entries are added.

## Git workflow

- Branch: `advisor/012-green-magenta-cct-tint`
- Conventional commits, matching `git log` (e.g.
  `feat(amaran): expose green/magenta tint for CCT lights`).
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Thread `gm` through `commands.py`

Add an optional `gm: int = 0` parameter to the three CCT builders and forward it.
Target shape:

```python
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


def brightness_cct_payloads(
    *, brightness: int, kelvin: int, power_on: bool = False, gm: int = 0
) -> list[bytes]:
    """Compatibility wrapper for callers that set brightness and CCT together."""
    return cct_payloads(brightness=brightness, kelvin=kelvin, power_on=power_on, gm=gm)
```

**Verify**: `python3 -m unittest discover -s tests` → `OK` (defaults keep all
existing callers identical).

### Step 2: Add G/M state + setter to `client.py`

2a. Add a module-level clamp beside the other `_clamp_*` helpers at the bottom of
`client.py`:

```python
def _clamp_green_magenta(value: Any) -> int:
    return max(-10, min(10, int(value)))
```

(`Any` is already imported in `client.py`. If it is not, add `from typing import
Any` — check the existing imports first.)

2b. In `__init__`, beside the desired-state fields (after `client.py:540`
`self._desired_active_color_mode = ...`), add:

```python
        self._desired_green_magenta: int = 0
```

2c. Add a read property next to `desired_active_color_mode` (around
`client.py:771`):

```python
    @property
    def green_magenta(self) -> int:
        """Return the cached green/magenta point applied to CCT commands."""

        return self._desired_green_magenta
```

2d. Update `async_set_brightness_cct` to use the stored G/M (or an explicit
override) and persist it. Add a `gm: int | None = None` keyword and resolve it:

```python
    async def async_set_brightness_cct(
        self,
        *,
        brightness: int,
        kelvin: int,
        power_on: bool = False,
        gm: int | None = None,
    ) -> None:
        """Send the Telink CCT payload carrying brightness and CCT."""

        brightness = _clamp_brightness(brightness)
        kelvin = _clamp_kelvin(kelvin)
        gm_value = (
            self._desired_green_magenta if gm is None else _clamp_green_magenta(gm)
        )
        sidus_intensity = round(brightness / 255 * 1000)
        payload = brightness_cct_payload(
            brightness=brightness, kelvin=kelvin, gm=gm_value
        )
        # keep the existing _LOGGER.debug(...) call as-is
        await self.async_send_siduses(
            cct_payloads(
                brightness=brightness,
                kelvin=kelvin,
                power_on=power_on,
                gm=gm_value,
            ),
            first_payload_delay=_POWER_SETTLE_DELAY if power_on else 0.0,
        )

        self._desired_power = True
        self._desired_brightness = brightness
        self._desired_color_temp_kelvin = kelvin
        self._desired_active_color_mode = COLOR_MODE_COLOR_TEMP
        self._desired_green_magenta = gm_value
```

2e. Add the two G/M entry points. Place them right after `async_set_cct`
(`client.py:1101-1110`):

```python
    def set_green_magenta_cached(self, gm: int) -> None:
        """Seed the optimistic green/magenta point without sending a command."""

        self._desired_green_magenta = _clamp_green_magenta(gm)

    async def async_set_green_magenta(self, gm: int) -> None:
        """Store the green/magenta point; re-send CCT if the light is on in CCT mode."""

        self._desired_green_magenta = _clamp_green_magenta(gm)
        if not (self._desired_power and self.supports_color_temp):
            return
        if self._desired_active_color_mode != COLOR_MODE_COLOR_TEMP:
            return
        if self._desired_color_temp_kelvin is None:
            return
        await self.async_set_brightness_cct(
            brightness=(
                self._desired_brightness
                if self._desired_brightness is not None
                else 255
            ),
            kelvin=self._desired_color_temp_kelvin,
        )
```

Note `async_set_green_magenta` never powers a light on: it returns early unless
`_desired_power` is already true (honors the AGENTS "no startup/unexpected
commands" rule).

**Verify**: `python3 -m unittest discover -s tests` → `OK`.

### Step 3: Create the `number.py` platform

Create `custom_components/amaran/number.py`, modeled on `sensor.py`:

```python
"""Green/magenta tint control for Amaran CCT lights."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberMode,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import AmaranSidusClient
from .const import DOMAIN, MANUFACTURER
from .fixtures import fixture_device_identifier


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the green/magenta number for CCT-capable lights."""

    clients: list[AmaranSidusClient] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AmaranGreenMagentaNumber(client)
        for client in clients
        if client.supports_color_temp
    )


class AmaranGreenMagentaNumber(RestoreNumber, NumberEntity):
    """Adjust the green/magenta point applied to CCT commands (-10..+10)."""

    _attr_has_entity_name = True
    _attr_name = "Green / magenta"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = -10
    _attr_native_max_value = 10
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:tune"

    def __init__(self, client: AmaranSidusClient) -> None:
        self._client = client
        self._attr_unique_id = (
            f"{client.ble_mac or client.address}_node_{client.node_address}_"
            f"src_{client.source_address}_green_magenta"
        )

    async def async_added_to_hass(self) -> None:
        """Restore the last tint without sending a command at startup."""

        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._client.set_green_magenta_cached(int(last.native_value))

    @property
    def available(self) -> bool:
        """Match the light's transport-based availability."""

        return self._client.is_available

    @property
    def native_value(self) -> float:
        """Return the cached green/magenta point."""

        return float(self._client.green_magenta)

    async def async_set_native_value(self, value: float) -> None:
        """Apply a new green/magenta point."""

        await self._client.async_set_green_magenta(int(value))
        self.async_write_ha_state()

    @property
    def device_info(self) -> dict[str, Any]:
        """Attach to the same device as the light."""

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
```

If `RestoreNumber` or `async_get_last_number_data` does not exist in the
installed Home Assistant (older core), **STOP and report** — do not silently drop
persistence.

### Step 4: Register the NUMBER platform in `__init__.py`

Change both platform tuples (`__init__.py:194` and `__init__.py:306`) from:

```python
    platforms = (Platform.LIGHT, Platform.SENSOR)
```
to:
```python
    platforms = (Platform.LIGHT, Platform.SENSOR, Platform.NUMBER)
```

**Verify**:
`grep -n "Platform.LIGHT, Platform.SENSOR)" custom_components/amaran/__init__.py`
→ **no matches** (both lines now end `Platform.NUMBER)`).

## Test plan

Model new client tests on the existing `PollTest` harness in `tests/test_client.py`
(`_make_client` builds a CCT-only client; `FakePollMesh` captures every
`async_send_siduses` call in `mesh.sent` as `(payloads, node_address)`).

1. **`tests/test_protocol.py`** — add to `class CctPayloadTest`:
   - `test_cct_payload_gm_zero_matches_neutral_capture`: assert
     `cct_payload_percent(percent=30, kelvin=5600, gm=0)` still equals
     `bytes.fromhex("31000000004001234b82")` (unchanged neutral capture).
   - `test_cct_payload_gm_offset_changes_bytes`: assert
     `cct_payload_percent(percent=30, kelvin=5600, gm=5)` **differs from** the
     `gm=0` bytes and from the `gm=-5` bytes.
   - `test_cct_status_decode_ignores_gm`: assert
     `decode_sidus_status_payload(cct_payload_percent(percent=30, kelvin=5600,
     gm=7), source_address=0x000B, destination_address=0x000F, sequence=1)`
     still decodes `color_temp_kelvin == 5600` and `color_mode == "color_temp"`
     (the decoder does not read G/M — documents that G/M is optimistic /
     write-only). Import `decode_sidus_status_payload` is already present in the
     test file.

2. **`tests/test_client.py`** — add a new `class GreenMagentaClientTest(
   unittest.IsolatedAsyncioTestCase)` reusing `PollTest._make_client` style
   (copy the helper or instantiate similarly with `FakePollMesh(ready=True)`):
   - `test_set_green_magenta_resends_cct_with_offset_when_on`: seed the client
     on in CCT mode (`client.set_cached_state(power=True, brightness=128,
     kelvin=4000, active_color_mode=COLOR_MODE_COLOR_TEMP)`), call
     `await client.async_set_green_magenta(6)`, assert the last captured payload
     equals `cct_payload_ha(brightness=128, kelvin=4000, gm=6)` (import
     `cct_payload_ha` from `custom_components.amaran.protocol`).
   - `test_set_green_magenta_does_not_send_when_off`: with `power` unset/false,
     call `await client.async_set_green_magenta(6)`, assert `mesh.sent == []`
     and `client.green_magenta == 6`.
   - `test_brightness_cct_uses_stored_green_magenta`: `client.set_green_magenta_cached(-4)`,
     then `await client.async_set_cct(brightness=200, kelvin=5000)`; assert the
     captured payload equals `cct_payload_ha(brightness=200, kelvin=5000, gm=-4)`.
   - `test_green_magenta_clamped_to_range`: `await client.async_set_green_magenta(99)`
     then assert `client.green_magenta == 10`; `-99` → `-10`.

3. **`tests/test_number.py`** (create) — model the HA-module stubbing on
   `tests/test_sensor.py` (read it first; it stubs `homeassistant.components.*`
   the same way other entity tests do). Cover:
   - The entity's `native_value` reflects a fake client's `green_magenta`.
   - `async_set_native_value(3.0)` awaits `client.async_set_green_magenta(3)`.
   - `async_setup_entry` only creates the entity for clients where
     `supports_color_temp` is true (pass one CCT client and one brightness-only
     client; expect exactly one entity).
   If stubbing `RestoreNumber` proves impractical in the unittest environment,
   it is acceptable to test the entity with a minimal fake that skips restore —
   but the three behaviors above must be asserted. Do **not** delete the
   `async_added_to_hass` restore logic to make a test pass.

**Verify**: `python3 -m unittest discover -s tests` → `OK`, and the new test
modules run green individually (`python3 -m unittest tests.test_number tests.test_client tests.test_protocol -v`).

## Done criteria

ALL must hold:

- [ ] `python3 -m unittest discover -s tests` exits 0, last line `OK`, with the
      new tests present and passing.
- [ ] `grep -n "Platform.LIGHT, Platform.SENSOR)" custom_components/amaran/__init__.py`
      returns no matches.
- [ ] `grep -n "gm" custom_components/amaran/commands.py` shows `gm` on all three
      CCT builders.
- [ ] `custom_components/amaran/number.py` exists and defines
      `AmaranGreenMagentaNumber`.
- [ ] `git status --porcelain` lists only the in-scope files.
- [ ] `plans/README.md` status row for 012 updated.

## STOP conditions

Stop and report (do not improvise) if:

- The "Current state" excerpts do not match the live files (drift since
  `49d7685`).
- `RestoreNumber` / `async_get_last_number_data` is unavailable in the target HA
  version.
- Adding `Platform.NUMBER` makes `async_forward_entry_setups` raise because the
  platform module fails to import — fix the import, or stop if the cause is
  outside `number.py`.
- A test fails twice after a reasonable fix attempt.
- You find yourself needing to edit `protocol.py`, `light.py`, `state.py`, or the
  HSI path to make this work — that means the approach diverged; stop.

## Maintenance notes

- G/M is **optimistic**: the CCT status decoder (`protocol.py:263-277`) does not
  read the G/M bits back, so the number reflects the last commanded value, not a
  device readback. If status decode is later extended to parse G/M, wire it into
  `client._handle_status_update`/`set_green_magenta_cached` so the number stays in
  sync.
- G/M only applies in CCT mode. A future HSI-mode G/M plan must pack the optional
  HSI CCT/G·M fields (`docs/protocol.md:116`) that are currently zeroed, and add
  an HSI branch to `async_set_green_magenta`.
- Reviewer should confirm: no command is sent when the light is off, defaults
  keep all pre-existing CCT captures byte-identical (the `gm=0` parity tests),
  and the new entity is `EntityCategory.CONFIG` (not a primary control).
- **Physical validation before merge** (AGENTS mandate): on a real Ace/Pano in
  CCT mode, move the slider and confirm the tint shifts green↔magenta and that
  turning the slider while the light is off does not turn it on.
