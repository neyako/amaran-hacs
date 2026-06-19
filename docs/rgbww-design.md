# RGBWW Full-Color Design

This spike records the RGBWW build gate for Amaran Ace/Pano lights. It does not
wire RGBWW into Home Assistant, add an encoder, or send any RGBWW command.

## Byte Layout

RGBWW is documented as the Java command type `0x04`, packed into a 10-byte Sidus
setter payload whose final byte is `0x84`. The byte order should follow the same
little-endian integer packing style used by the current Sidus builders in
`custom_components/amaran/protocol.py`.

Candidate raw expression before checksum:

```text
(intensity << 12)
| (cool_white << 22)
| (warm_white << 32)
| (blue << 42)
| (green << 52)
| (red << 62)
| (0x84 << 72)
```

| Byte or bits | Field | Value | Evidence |
| --- | --- | --- | --- |
| byte 0 | checksum | `sidus_checksum(payload)` | Documented by current Sidus helpers |
| bits 8..11 | unused / zero | `0x0` | Inferred from the documented field start at bit 12 |
| bits 12..21 | intensity | 10-bit value | Documented in `docs/protocol.md` |
| bits 22..31 | cool white | 10-bit value | Documented in `docs/protocol.md` |
| bits 32..41 | warm white | 10-bit value | Documented in `docs/protocol.md` |
| bits 42..51 | blue | 10-bit value | Documented in `docs/protocol.md` |
| bits 52..61 | green | 10-bit value | Documented in `docs/protocol.md` |
| bits 62..71 | red | 10-bit value | Documented in `docs/protocol.md` |
| byte 9 | setter byte | `0x84` | Documented in `docs/protocol.md` |

The layout evidence is strong enough to describe the payload, but not strong
enough to ship RGBWW support. The mixed RGB plus white behavior still needs a
physical capture.

## Open Questions The Capture Must Answer

| Question | Value to record | Why it blocks the build |
| --- | --- | --- |
| Does the light accept simultaneous nonzero RGB and white channels? | Yes/no for mixed red/green/blue plus cool/warm white; record any clamping, ignored channel group, or app-side refusal. | If the light treats RGB and white as mutually exclusive, `ColorMode.RGBWW` would misrepresent the device. |
| What is the channel scale? | `0..1000`, `0..1023`, or another captured max for each of red, green, blue, cool white, warm white, and intensity. | HA supplies `0..255`; the encoder must choose a deterministic device scale. |
| Does an RGBWW setter imply power-on? | Yes/no when the light starts off, plus whether status reports show power on afterward. | Existing setters often act as active state changes; startup and service behavior must not surprise users. |
| Are zero RGB plus nonzero white values accepted as a white mode? | Yes/no, with captured pure-white payload and observed light output. | Determines whether RGBWW can cover white-channel use without falling back to CCT. |
| Are zero white plus nonzero RGB values equivalent to current HSI output? | Yes/no, with captured pure-RGB payload and observed light output. | Helps evaluate HS-to-RGBWW migration impact. |

## HA Modeling

Home Assistant's RGBWW model is `ColorMode.RGBWW` with `rgbww_color` as
`(red, green, blue, cool_white, warm_white)`, where each channel is `0..255`.
The future encoder should clamp each HA channel to `0..255`, then convert with
the same half-up rounding style as `_ha_brightness_to_intensity`:

```text
device_channel = round_half_up(ha_channel / 255 * device_channel_max)
```

`device_channel_max` must come from capture. If the app uses the same practical
scale as intensity, use `1000`; if capture proves it uses the full 10-bit range,
use `1023`. Intensity should continue to come from HA brightness using
`_ha_brightness_to_intensity`, so brightness remains `0..255` mapped to
`0..1000`.

For supported Ace/Pano lights, the future entity should keep existing
brightness and color-temperature support while adding RGBWW:

```text
supported_color_modes = {BRIGHTNESS, COLOR_TEMP, RGBWW}
```

When a service call supplies `rgbww_color`, the active mode should become
`RGBWW` and the entity should report `rgbww_color`. When a service call supplies
`color_temp_kelvin`, the active mode should remain `COLOR_TEMP`. Brightness-only
changes should preserve the current active color mode, as the existing light path
does for HS/CCT state.

RGBWW should supersede HS for these models. Advertising both `HS` and `RGBWW`
would imply two independent color models for the same hardware and can lose the
warm/cool white channels. The build should therefore remove `HS` from
Ace/Pano's advertised modes when RGBWW is enabled. That is a visible migration:
existing user automations that explicitly send or inspect `hs_color` on Ace/Pano
may need release-note guidance and tests around HA service behavior.

## Model Gating

RGBWW must be gated to the two RGB-capable models named in the current product
catalog and agent rules:

- Ace 25c, catalog hex `400U5`
- Pano 60c, catalog hex `400W5`

The build should resolve the imported light through `lookup_product` and gate on
stable catalog identity, preferably `hex in {"400U5", "400W5"}`. If the project
later adds a capability helper, it should derive from that same catalog identity
or an explicit side table, not from fuzzy display names.

Do not advertise RGBWW for 60x S, 100x S, Verge, Go, or any other CCT-only
model. If product metadata is missing or ambiguous, default to the current
non-RGBWW modes.

## Capture & Validation Procedure

Reuse the capture path from `docs/effects-design.md`, but trigger RGBWW states in
the official Amaran app instead of system effects.

1. Use an Ace 25c (`400U5`) or Pano 60c (`400W5`) already imported with known
   mesh credentials and a reachable Bluetooth Mesh proxy.
2. Enable debug logging for the Amaran integration and verify the diagnostic
   path with `amaran.request_power_status`.
3. Add local, non-shipping capture instrumentation for decrypted Mesh Proxy Data
   In writes, or use an equivalent BLE/GATT capture that yields decrypted payload
   bytes.
4. In the official app, set a pure RGB state with nonzero RGB and zero warm/cool
   white. Capture the decrypted write and isolate the 10-byte Sidus payload.
5. Set a pure white state with zero RGB and nonzero warm/cool white. Capture the
   payload.
6. Set a mixed state with nonzero RGB and nonzero warm/cool white. Capture the
   payload.
7. For each capture, record model, firmware version, app version, whether the
   light was initially off, full payload hex, checksum validity, decoded field
   values, and visible output.
8. Compare the captured bytes to the documented layout: byte 9 `0x84`, intensity
   bits `12..21`, cool white `22..31`, warm white `32..41`, blue `42..51`, green
   `52..61`, red `62..71`, and checksum in byte 0.
9. Commit the captured hex and decoded values into the future build plan or
   protocol docs before any shipped encoder is wired to Home Assistant.

The required three captures are pure RGB, pure white, and mixed RGB plus white.
The mixed capture is the hard gate.

## Decision Record

| Topic | Current evidence | Decision |
| --- | --- | --- |
| Byte layout | Documented from decompiled app sources and summarized in `docs/protocol.md`. | Layout can be used for design and later structural tests. |
| Channel scale | Unknown without capture. | Build blocked until scale is recorded. |
| Simultaneous RGB plus white | Explicitly unproven. | Build blocked until mixed-channel capture proves behavior. |
| HA mode | `RGBWW` is the only HA mode that preserves independent warm/cool white. | Recommend `RGBWW` for Ace/Pano after capture, superseding `HS`. |
| CCT-only models | Agent rules and catalog facts limit RGB capability to Ace/Pano. | No RGBWW outside Ace/Pano. |

Go/no-go: no-go for shipped RGBWW support today. The layout is documented, but
the build remains blocked on real-light capture of mixed RGB plus white behavior.
No dormant encoder was added in this spike.

## Follow-Up Build Plan Outline

A future RGBWW build plan should:

- add `rgbww_payload` in `custom_components/amaran/protocol.py` using captured
  byte parity, not Java layout alone;
- add an RGBWW command builder in `custom_components/amaran/commands.py`;
- add `AmaranSidusClient.async_set_rgbww` without sending commands during
  startup;
- gate RGBWW capability to Ace 25c (`400U5`) and Pano 60c (`400W5`);
- wire `ColorMode.RGBWW` / `rgbww_color` in `custom_components/amaran/light.py`
  and remove `HS` from Ace/Pano advertised modes when RGBWW is enabled;
- add tests for payload bytes, HA-to-device channel scaling, model gating,
  active color-mode reporting, and migration behavior for existing HS-capable
  entries;
- validate power, brightness, CCT, RGBWW pure RGB, RGBWW pure white, RGBWW mixed
  RGB plus white, restart, transport reconnect, and ESPHome proxy restart on
  physical hardware.
