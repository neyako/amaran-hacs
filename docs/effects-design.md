# System Effects Design

This spike records a build gate for Amaran system effects. It does not wire an
effect into Home Assistant, add an entity feature, or send an effect command.

## Target Scope

The first build should target the first-generation system-effect command family
only: command type `0x07` on the two RGB-capable models with the strongest local
evidence, Ace 25c (`400U5`) and Pano 60c (`400W5`). Within that family, the only
effect with a concrete local byte layout is Candle, effect type `0x04`, plus the
required effect-off command, effect type `0x0f`.

That makes the initial target:

- Ace 25c (`400U5`): Candle, then off.
- Pano 60c (`400W5`): Candle, then off.

Other first-generation effects should be added only after their APK layout and
per-model support are recorded. Second-generation effects (`0x22` / decimal
`34`) are deferred because their layouts carry more mode-dependent fields and
there is no in-repo real-light capture.

## Byte Layout

All candidate effect payloads are 10-byte Sidus payloads. Byte 0 is the Sidus
checksum set by `sidus_checksum` / `_finalize_sidus`; byte 9 is the command type.
Bit positions below use the same little-endian integer packing style as the
existing payload builders in `custom_components/amaran/protocol.py`.

### Candle (`0x07` / `0x04`)

Raw candidate expression before checksum:

```text
(cct << 40) | (frequency << 50) | (intensity << 54) | (0x04 << 64) | (0x07 << 72)
```

| Byte or bits | Field | Value | Evidence |
| --- | --- | --- | --- |
| byte 0 | checksum | `sidus_checksum(payload)` | Documented by current Sidus helpers |
| bytes 1-4 | unused / zero | `0x00` | Inferred; not described by `docs/protocol.md` |
| bits 40-49 | CCT | 10-bit value | Documented layout; scale needs capture |
| bits 50-53 | frequency | 4-bit value | Documented layout; range/default needs capture |
| bits 54-63 | intensity | 10-bit value | Documented layout; range/default needs capture |
| byte 8 | effect type | `0x04` | Documented |
| byte 9 | command type | `0x07` | Documented |

The field locations are documented in `docs/protocol.md`. The safe HA-facing
defaults, units, and exact value scaling are not captured in this checkout.

### Effect Off (`0x07` / `0x0f`)

Raw candidate expression before checksum:

```text
(0x0f << 64) | (0x07 << 72)
```

| Byte or bits | Field | Value | Evidence |
| --- | --- | --- | --- |
| byte 0 | checksum | `sidus_checksum(payload)` | Documented by current Sidus helpers |
| bytes 1-7 | unused / zero | `0x00` | Inferred; candidate encoder should keep them zero until capture proves otherwise |
| byte 8 | effect type | `0x0f` | Documented |
| byte 9 | command type | `0x07` | Documented |

The command/effect bytes are documented. Model-family behavior and any hidden
state-reset side effects are not captured.

## Per-Model Effect Side-Table

Do not add effect data to `custom_components/amaran/product.json`; that file is a
refreshable mirror of the Desktop product catalog. Per-model effects should live
in a separate file, `custom_components/amaran/product_effects.json`, keyed by the
same product identity used by catalog lookup. A model absent from this table
exposes no effects.

Proposed shape:

```json
{
  "version": 1,
  "effects_by_hex": {
    "400U5": {
      "product_id": null,
      "model": "amaran Ace 25c",
      "effect_list": ["Candle"],
      "effects": {
        "Candle": {
          "generation": "first_gen",
          "command_type": "0x07",
          "effect_type": "0x04",
          "encoder": "first_gen_candle",
          "parameters": {
            "cct": {"bits": "40..49", "evidence": "documented", "default": null},
            "frequency": {"bits": "50..53", "evidence": "documented", "default": null},
            "intensity": {"bits": "54..63", "evidence": "documented", "default": null}
          },
          "capture": null
        }
      }
    }
  }
}
```

The future build should refuse to expose an effect whose side-table row lacks
captured or otherwise explicitly approved defaults. `EFFECT_OFF` is not a
separate product effect; it is the common off command used to leave an active
effect.

## Home Assistant Modeling

Effects should be exposed only for a light whose model resolves to a side-table
row with a non-empty verified `effect_list`. Those lights add
`LightEntityFeature.EFFECT`; all other models keep their current feature set.

The light entity should populate `effect_list` from the ordered side-table names.
In `async_turn_on`, `ATTR_EFFECT` handling should:

- send effect-off when the requested effect is `EFFECT_OFF`;
- send the matched side-table encoder when the requested effect is in
  `effect_list`;
- reject unknown effects without falling back to a generic command.

The reported active effect should be `EFFECT_OFF` when no effect is active. A
Candle-style first-generation CCT effect should report a color-temperature mode
while active; future HSI-style effects can choose an HS mode only when their
layout actually carries HSI fields. Startup restoration must remain command-free:
do not start an effect, turn a light on, or send off during Home Assistant
startup.

This follows the Home Assistant light entity contract already linked from
`docs/protocol.md`: expose verified `effect_list` values, accept `ATTR_EFFECT`,
report `EFFECT_OFF` when idle, and use a color mode that matches the active
effect's color model.

## Capture & Validation Procedure

Before any build ships, validate at least one targeted effect on real Ace/Pano
hardware:

1. Use a light already imported with known mesh credentials and a reachable
   Bluetooth Mesh proxy.
2. Enable debug logging for the Amaran integration and verify the existing
   diagnostic path by calling `amaran.request_power_status`; that service already
   logs decrypted Mesh Proxy Data Out reports.
3. Add local, non-shipping capture instrumentation for the same decrypt/format
   path to record Mesh Proxy Data In writes, or use an equivalent BLE/GATT
   capture that yields decrypted payload bytes.
4. In the official Amaran app, trigger Candle on Ace 25c or Pano 60c.
5. Capture the decrypted Mesh Proxy Data In write, isolate the 10-byte Sidus
   payload, and record the full hex string.
6. Compare the captured bytes to the documented first-generation layout:
   command byte `0x07`, effect byte `0x04`, CCT bits `40..49`, frequency bits
   `50..53`, intensity bits `54..63`, valid checksum in byte 0.
7. Trigger effect off in the official app, capture the off payload, and confirm
   command byte `0x07`, effect byte `0x0f`, and checksum.
8. Repeat the generated payload through a capture-only branch and confirm the
   light visibly enters and leaves the effect.
9. Commit the captured hex, model, firmware/app version, and observed defaults
   into the future build plan or protocol docs.

The build plan is blocked until at least one targeted effect round-trips on
hardware. A Java layout alone is not enough to ship.

## Decision Record

| Target | Evidence strength | Recommendation |
| --- | --- | --- |
| Candle on Ace 25c (`400U5`) | Byte layout documented; zero padding and defaults inferred; no capture | Design ready; build needs capture |
| Candle on Pano 60c (`400W5`) | Byte layout documented; per-model support inferred from app/systemfx notes; no capture | Design ready; build needs capture |
| Effect off (`0x07` / `0x0f`) | Command/effect bytes documented; model-family behavior unverified; no capture | Build only with the first captured effect |
| Other first-generation effects | Mentioned as an app family; local decompiled sources absent | Defer until APK layout plus capture are recorded |
| Second-generation effects (`0x22`) | Example Lightning II layout documented but mode-dependent and uncaptured | Defer |

Go/no-go: the design is ready, but the build is gated on real-light capture.

## Follow-Up Build Plan Outline

A future `plans/0NN-effects-build.md` should:

- add first-generation encoder functions in `custom_components/amaran/protocol.py`
  with captured hex in tests;
- add command builders in `custom_components/amaran/commands.py`;
- add a client method that sends effect payloads without changing startup
  behavior;
- add `custom_components/amaran/product_effects.json` and a loader that joins by
  catalog identity;
- wire `effect_list`, `LightEntityFeature.EFFECT`, `ATTR_EFFECT`, and
  `EFFECT_OFF` handling in `custom_components/amaran/light.py`;
- add unit tests for payloads, side-table defaults, and light entity effect
  modeling;
- validate power, brightness, CCT, HSI, effect on/off, HA restart, proxy
  reconnect, and ESPHome proxy restart on physical hardware.
