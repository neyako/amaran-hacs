# Telemetry Entities Design

## Data already available

Battery-capable lights already deliver a decoded Sidus `0x0A` power report. The
live protocol model is `SidusPowerInfo` with these fields:

| Field | Meaning | Surface |
|---|---|---|
| `power_supply_mode` | `"battery"` or `"ac"` | User-meaningful |
| `battery_time_minutes` | Runtime value reported by the light | User-meaningful, with a semantics spot-check before final labeling |
| `battery_percentage` | Battery percentage | Already surfaced by the existing Battery sensor |
| `battery_voltage` | Battery voltage in millivolts | User-meaningful diagnostic |
| `external_voltage` | External input voltage in millivolts | User-meaningful diagnostic |
| `command_type` | Sidus report command id | Internal diagnostics only |
| `operation_type` | Sidus report operation bit | Internal diagnostics only |
| `source_address` | Report source address | Internal diagnostics only |
| `destination_address` | Report destination address | Internal diagnostics only |
| `sequence` | Report sequence number | Internal diagnostics only |

`AmaranSidusClient._handle_power_info_update` already stores the decoded packet
as `client.battery_power_info` with these dict keys:

`power_supply_mode`, `battery_time_minutes`, `battery_percentage`,
`battery_voltage`, `external_voltage`, `command_type`, `operation_type`,
`source_address`, `destination_address`, `sequence`, and `received_at`.

No new decoding or hardware capture is required for the proposed telemetry
surface. This is presentation only: read fields that already decode, already
reach the client, and already ship today as Battery sensor attributes.

## Proposed entities

| Entity | Platform | Source field | HA typing | Default posture |
|---|---|---|---|---|
| Running on battery | `binary_sensor` | `power_supply_mode == "battery"` | Plain binary sensor, no device class | Enabled by default, diagnostic |
| Battery runtime | `sensor` | `battery_time_minutes` | `device_class = DURATION`, `native_unit_of_measurement = "min"`, `state_class = MEASUREMENT` | Enabled by default, diagnostic |
| Battery voltage | `sensor` | `battery_voltage` mV to V | `device_class = VOLTAGE`, `native_unit_of_measurement = "V"`, `state_class = MEASUREMENT` | Disabled by default, diagnostic |
| External voltage | `sensor` | `external_voltage` mV to V | `device_class = VOLTAGE`, `native_unit_of_measurement = "V"`, `state_class = MEASUREMENT` | Disabled by default, diagnostic |

The existing Battery percentage sensor remains the percent surface and does not
need to be duplicated.

For the power-source entity, `device_class = BATTERY_CHARGING` is wrong because
the decoded field says whether the light is powered by battery or external
power, not whether a battery is charging. `device_class = "power"` is also a poor
fit for a "Running on battery" entity because Home Assistant's power class reads
as on when power is present; that would be clearer for an "On external power"
entity, but less direct for the automation use case. A plain binary sensor keeps
the state semantics explicit: on means the light is running on battery, off means
a real packet reported AC.

## Availability & never invent values

Every proposed entity must be unavailable until a real decoded packet exists.
The availability rule is:

`client.battery_power_info is not None` and the entity's source field is present.

This mirrors the current Battery sensor behavior, where `available` is false
until `native_value` has a real value. Missing data returns `None` and must not
be converted into fallback values.

The Running on battery binary sensor is unavailable before the first packet. It
must not report off before evidence arrives, because that would assert "on AC"
without a real decoded report.

The voltage sensors convert millivolts to volts only after their source field is
present. They must not fabricate `0 V`, `100%`, or any other placeholder.

## Wiring plan (for the build, not now)

The follow-up build should make additive, read-only entity changes only:

1. Add `Platform.BINARY_SENSOR` to the setup tuple at `__init__.py:194` and the
   unload tuple at `__init__.py:306`.
2. Create `binary_sensor.py` modeled on `sensor.py`: same `async_setup_entry`
   shape, same `device_info` pattern, same `fixture_device_identifier` device
   identity, and the same `subscribe_battery` subscription in
   `async_added_to_hass`.
3. Gate the Running on battery entity on `client.battery_capable`, matching the
   current Battery sensor setup gate.
4. Add Battery runtime, Battery voltage, and External voltage sensors either
   beside `AmaranSidusBatterySensor` in `sensor.py` or in a new telemetry-focused
   sensor module if that keeps the build cleaner.
5. Follow the existing unique-id convention from `sensor.py`:
   `f"{ble_mac or address}_node_{node}_src_{source}_<suffix>"`.
6. Keep command, address, and sequence details out of user-facing entities; they
   remain diagnostic attributes only.

This spike does not change any platform tuple, entity module, client code,
protocol code, or command path.

## Model gating & terminology

Telemetry entities are created only for lights where `client.battery_capable` is
true. Non-battery-capable models receive no new telemetry entities.

Proposed user-facing entity names:

| Entity | Name |
|---|---|
| Power source binary sensor | Running on battery |
| Runtime sensor | Battery runtime |
| Battery voltage sensor | Battery voltage |
| External voltage sensor | External voltage |

Use light-friendly wording in names and UI strings. Do not expose transport,
proxy, or mesh wording in user-facing telemetry entities. Those internals remain
limited to diagnostics and logs.

## Decision record

Decision: GO, buildable now without hardware capture.

Reason: unlike RGBWW or effects work, this telemetry does not require a new
packet capture or a new decoder. The decoded `SidusPowerInfo` data already flows
through the client and is already visible as Battery sensor attributes. The
follow-up build can surface it as read-only Home Assistant entities while
preserving the existing command and startup behavior.

Residual real-hardware check: confirm `battery_time_minutes` semantics against a
real battery packet before trusting the "Battery runtime" label. The expected
meaning is minutes remaining, but the build should do a quick physical-light
spot-check to rule out elapsed time or another vendor-specific interpretation.
This is a label-validation check, not a blocker for the entity design.

## Follow-up build plan outline

1. Add pure telemetry value helpers that accept `client.battery_power_info` and
   return a typed value or `None`.
2. Add focused unit tests for helper behavior, including `None`, missing fields,
   and millivolt-to-volt conversion.
3. Add `binary_sensor.py` with the Running on battery entity, gated to
   `client.battery_capable` and subscribed to battery updates.
4. Add Battery runtime, Battery voltage, and External voltage sensors with the
   same unavailable-until-real contract.
5. Add `Platform.BINARY_SENSOR` to both setup and unload platform tuples.
6. Run the relevant unit tests, then the full `python3 -m unittest discover -s
   tests` suite.
7. Perform a physical spot-check on a battery-capable light to validate
   `battery_time_minutes` semantics and confirm the entities stay unavailable
   until the first decoded packet.
