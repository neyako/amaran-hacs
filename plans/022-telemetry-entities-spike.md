# Plan 022: Spike — design power-source + runtime telemetry entities from decoded data

> **Executor instructions**: This is a **design spike**, not a build. The
> deliverable is a written design + decision record, plus (optionally) one small
> pure-logic mapping module with unit tests. **Do not add a new entity platform,
> do not modify `__init__.py`'s platform list, and do not wire any new entity into
> Home Assistant in this spike.** Honor every STOP condition. When done, update the
> status row in `plans/README.md` — unless a reviewer dispatched you and told you
> they maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 2193a35..HEAD -- custom_components/amaran/protocol.py custom_components/amaran/client.py custom_components/amaran/sensor.py custom_components/amaran/__init__.py`
> If any changed, compare the "Current state" excerpts below against the live code
> before writing the design.

## Status

- **Priority**: P3
- **Effort**: S–M (design-heavy)
- **Risk**: LOW (docs + optional dormant pure code)
- **Depends on**: none
- **Category**: direction (feature research)
- **Planned at**: commit `2193a35`, 2026-06-20

## Why this matters

Battery-capable Amaran lights already report a full power/battery packet that the
integration **fully decodes today** — `SidusPowerInfo` carries `power_supply_mode`
(`"battery"`/`"ac"`), `battery_time_minutes` (runtime remaining), `battery_voltage`,
and `external_voltage` (`protocol.py:46-60`, decoded at `protocol.py:297-333`).
But none of that is surfaced as first-class Home Assistant state: it lives only as
free-form **attributes** on the battery sensor (`sensor.py:158-161` returns
`client.battery_power_info`). So a user can read "% battery" but cannot, for
example, automate on "running on battery" or chart "minutes of runtime left",
because those are buried in an attributes blob, not entities with device classes.

Unlike the effects (014) and RGBWW (015) spikes — which are **blocked on a real
hardware capture** — this data already flows and is already proven correct
(battery % is shipped from it). So this is the cheapest real feature on the board:
purely additive read-only entities over data the integration already has. This
spike produces the design + go/no-go so a follow-up build plan can wire the
entities safely and consistently with the AGENTS.md rules.

## Current state (what already exists)

- **Decoded model** — `SidusPowerInfo` (`protocol.py:46-60`):
  ```python
  @dataclass(frozen=True)
  class SidusPowerInfo:
      power_supply_mode: str        # "battery" or "ac"
      battery_time_minutes: int     # runtime remaining
      battery_percentage: int
      battery_voltage: int          # millivolts
      external_voltage: int         # millivolts
      command_type: int
      operation_type: int
      source_address: int
      destination_address: int
      sequence: int
  ```
- **It already reaches the client** — `AmaranSidusClient._handle_power_info_update`
  (`client.py:1278-1315`) is subscribed via `subscribe_access` for battery-capable
  lights (`client.py:891-894`), validates the source node, and stores a dict on
  `self._battery_power_info`, exposed by the `battery_power_info` property
  (`client.py:707-710`). The dict keys are `power_supply_mode`,
  `battery_time_minutes`, `battery_percentage`, `battery_voltage`,
  `external_voltage`, `command_type`, `operation_type`, `source_address`,
  `destination_address`, `sequence`, `received_at`.
- **It is polled** — battery is polled every 60 s (`client.py:926-929`,
  `DEFAULT_BATTERY_POLL_INTERVAL_SECONDS`); `subscribe_battery` (`client.py:836-845`)
  notifies entities when a new packet decodes.
- **Today's only surface** — `AmaranSidusBatterySensor.extra_state_attributes`
  (`sensor.py:158-161`) returns `client.battery_power_info`. The battery % sensor
  is `available` only when a real value exists (`sensor.py:151-155`) — never
  invented.
- **Platforms forwarded** — `__init__.py:194`
  `(Platform.LIGHT, Platform.SENSOR, Platform.NUMBER)` (and the matching unload at
  `__init__.py:306`). A new `binary_sensor` would require adding
  `Platform.BINARY_SENSOR` here in the **build**, not this spike.

Binding constraints from `AGENTS.md` the design must honour:

- **"Battery … Do not invent values. Do not fake 0% or 100%."** — every proposed
  entity must be `unavailable` until a real packet arrives, exactly like the
  existing battery sensor.
- **"User Terminology"** — user-facing names use *light/lights*; never expose
  *transport*, *proxy*, or *mesh* (those stay in diagnostics only).
- **Capability Mapping / Battery** — telemetry entities are gated to
  battery-capable lights (`client.battery_capable`, `client.py:694-698`), like the
  battery sensor (`sensor.py:38-42`).

## Commands you will need

Run from the repo root (`/Users/neyako/Documents/hacs-amaran`).

| Purpose | Command | Expected |
|---|---|---|
| Full suite | `python3 -m unittest discover -s tests` | last line `OK`, **178** tests |
| Protocol/telemetry tests (only if Phase B) | `python3 -m unittest tests.test_telemetry -v` | `OK` |

**Do not use `pytest`** (intercepted). Use `unittest`.

## Scope

**In scope**:
- `docs/telemetry-design.md` (create) — design + decision record.
- **Phase B only, optional (and only if the operator asks):**
  `custom_components/amaran/telemetry.py` (create — pure mapping helpers, no HA
  imports, unreferenced by any entity) + `tests/test_telemetry.py` (create).

**Out of scope** (do NOT touch in this spike):
- `__init__.py` — do not add `Platform.BINARY_SENSOR` or change the platform
  tuples. That is the build.
- `sensor.py`, `client.py`, `protocol.py`, `light.py`, `number.py` — no entity is
  added or rewired here.
- Sending any new command to a real light (telemetry is read-only anyway).

## Deliverable 1 (required): `docs/telemetry-design.md`

Write a design document with these sections (use `## ` headings so the Done
criteria grep finds them):

1. **Data already available** — transcribe the `SidusPowerInfo` fields and the
   `battery_power_info` dict keys from the excerpts above, marking which are
   user-meaningful (`power_supply_mode`, `battery_time_minutes`,
   `battery_voltage`, `external_voltage`) vs internal (`command_type`,
   `operation_type`, addresses, `sequence`). State plainly: **no new decoding or
   hardware capture is required** — this is presentation only.
2. **Proposed entities** — a table mapping each entity to its source field and HA
   typing. Recommended set:
   | Entity | Platform | Source field | HA typing |
   |---|---|---|---|
   | On battery | `binary_sensor` | `power_supply_mode == "battery"` | `device_class = BATTERY_CHARGING` is wrong — analyse: likely `device_class = "power"` (on=AC) or a plain on/off "Running on battery"; recommend one and justify |
   | Runtime remaining | `sensor` | `battery_time_minutes` | `device_class = DURATION`, `native_unit_of_measurement = "min"`, `state_class = MEASUREMENT` |
   | Battery voltage | `sensor` (diagnostic, disabled by default) | `battery_voltage` mV → V | `device_class = VOLTAGE`, unit `"V"` |
   Decide for each: enabled-by-default or diagnostic/disabled. Keep parity with the
   existing battery sensor's diagnostic posture where sensible.
3. **Availability & "never invent values"** — specify that each entity is
   `available` only when `client.battery_power_info is not None` and the relevant
   field is present, mirroring `sensor.py:151-155`. Spell out the
   on-battery binary sensor's behaviour before the first packet (unavailable, not
   "off") so it never asserts "on AC" without evidence.
4. **Wiring plan (for the build, not now)** — describe exactly what the build will
   change: add `Platform.BINARY_SENSOR` to the tuples at `__init__.py:194` and
   `:306`; create `binary_sensor.py` modelled on `sensor.py` (same
   `async_setup_entry` shape, `device_info`, `fixture_device_identifier`,
   `subscribe_battery` subscription in `async_added_to_hass`, gate on
   `client.battery_capable`); add the runtime/voltage sensors either to `sensor.py`
   alongside `AmaranSidusBatterySensor` or in the new file. Note the unique-id
   convention to follow (`sensor.py:182-197`:
   `f"{ble_mac or address}_node_{node}_src_{source}_<suffix>"`).
5. **Model gating & terminology** — gate to `client.battery_capable`; user-facing
   names use *light*-friendly wording, no transport/proxy/mesh. Give the proposed
   entity names (e.g. "Running on battery", "Battery runtime", "Battery voltage").
6. **Decision record (go/no-go)** — unlike RGBWW/effects, expected honest outcome
   is **GO, buildable now without hardware capture**, because the data already
   decodes and ships in battery attributes. Note the one residual risk to validate
   on real hardware: confirm `battery_time_minutes` semantics (minutes remaining vs
   elapsed) against a real packet before trusting the "Runtime remaining" label —
   recommend a quick check, not a blocker.
7. **Follow-up build plan outline** — the ordered steps a future build plan takes
   (helpers → binary_sensor.py → sensors → `__init__` platform forward → tests →
   physical spot-check), each small and independently verifiable.

**Verify**: `test -f docs/telemetry-design.md` and
`grep -cE "^## " docs/telemetry-design.md` → at least `7`.

## Deliverable 2 (OPTIONAL — only if the operator wants dormant helpers now)

Only if explicitly requested. If you do, keep it **pure** (no Home Assistant
imports, not referenced by any entity), so it cannot affect runtime:

- Create `custom_components/amaran/telemetry.py` with small total functions over
  the `battery_power_info` dict shape, each returning a value **or `None`** when
  the data is absent (never a fabricated default):
  ```python
  def power_source_is_battery(info: dict | None) -> bool | None:
      """True on battery, False on AC, None when unknown."""
      if not info or "power_supply_mode" not in info:
          return None
      return info["power_supply_mode"] == "battery"

  def runtime_remaining_minutes(info: dict | None) -> int | None:
      if not info:
          return None
      value = info.get("battery_time_minutes")
      return int(value) if value is not None else None

  def battery_volts(info: dict | None) -> float | None:
      if not info:
          return None
      mv = info.get("battery_voltage")
      return round(int(mv) / 1000, 3) if mv else None
  ```
- Add `tests/test_telemetry.py` (plain `unittest.TestCase`, model after
  `tests/test_state.py`) asserting: known dict → expected value; `None`/empty dict
  → `None` for each helper (the "never invent values" contract).

**Verify**: `python3 -m unittest tests.test_telemetry -v` → `OK`; and
`grep -rn "telemetry" custom_components/amaran/__init__.py custom_components/amaran/sensor.py`
→ **no matches** (the module stays dormant/unwired).

## Done criteria

- [ ] `docs/telemetry-design.md` exists with at least the seven `## ` sections.
- [ ] The design names a concrete entity set with source field + HA device class
      for each, and the enabled/diagnostic posture per entity.
- [ ] The design states that no new decode/capture is needed and gates entities to
      `client.battery_capable`.
- [ ] The design's availability section makes every entity unavailable-until-real,
      consistent with `sensor.py:151-155` and the AGENTS "do not invent values" rule.
- [ ] No entity/platform/transport file modified; `__init__.py` platform tuples
      unchanged (`git status --porcelain` shows only `docs/telemetry-design.md`, plus
      `telemetry.py` + `tests/test_telemetry.py` if Phase B was requested).
- [ ] If Phase B done: `python3 -m unittest discover -s tests` → `OK`; `telemetry.py`
      is unreferenced by any entity module.
- [ ] `plans/README.md` status row for 022 updated.

## STOP conditions

Stop and report (do not improvise) if:

- You start editing `__init__.py`, `sensor.py`, or creating a wired
  `binary_sensor.py` — that is the build, not this spike.
- The design appears to require new protocol decoding or a hardware capture to
  surface a proposed field — drop that field (or mark it build-time-validate) and
  keep the spike to data that already decodes.
- A proposed entity cannot honour "unavailable until a real packet" — redesign it;
  do not ship an entity that asserts a value without evidence.

## Maintenance notes

- This is the one direction item with **no hardware gate** — the build can proceed
  straight from the design. Keep the build plan additive and read-only; it must not
  touch the command/transport path (no physical-light validation gate beyond a
  one-time `battery_time_minutes` semantics check).
- When the build lands `Platform.BINARY_SENSOR`, both the setup forward
  (`__init__.py:194`) and the unload (`__init__.py:306`) tuples must change together,
  or unload will leak the platform.
- Keep `command_type`/`operation_type`/addresses/`sequence` out of user-facing
  entities — they belong in diagnostics only (AGENTS terminology rule).
