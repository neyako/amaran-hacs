# Built-in System Effects

## Implemented behavior

All 33 built-in system-effect variants represented in Desktop 1.1.03 (129)
are implemented as native HA effect presets. A light exposes only the variants
listed by its Desktop `systemfx_*` flags and only if it supports HSI or RGB.
Ace, Pano, and Ray color profiles expose their 12 enabled first-generation
effects; other models have their own subsets. A catalog flag is capability
evidence, not a physical test result.

Encoding is shared across all eligible HSI/RGB models; there are no Ace/T4c
model-specific packet paths. The native **Effect preset** select entity makes
the chooser visible directly on the device page. It mirrors the light entity
and delegates to `light.turn_on`, so both controls use the same state and encoder.
It displays `off` when the light is off; selecting `off` then sends no command.

Select a preset with `light.turn_on` and `effect`. HA brightness controls its
intensity. Brightness changes reapply the preset. `effect: off` stops the current
generation correctly and returns to the cached plain color mode. Selecting a
plain color also leaves effect mode. Power off preserves the selected preset
for the next explicit turn-on. Restart restores cached state without commands.
While the light is off, effect-off clears the cached selection without sending
a stop packet; the following wake/color command selects the normal mode.

This pass covers built-in presets, as requested. Pixel/music effects are out of
scope. Per-effect parameter editors are not exposed; presets use the values
below rather than retaining arbitrary settings made in the official app.

## Encoding evidence

Source: the original checkout's decompiled app classes under
`artifacts/jadx/sources/com/sidus/link/`:

- `coremesh/SystemEffectPacker.java` and `libmesh/protocol/ProtocolConstant.java`
  define command/effect IDs.
- `libmesh/protocol/*Protocol.java`, `*Protocol2.java`, and `*Protocol3.java`
  define exact field layouts.
- `coremesh/*Effect.java` and `*IIEffect.java` define first/second-generation
  preset defaults and command sequences.

The setter operation bit is set: wire command bytes are **0x87** and **0xa2**.
Effect ID occupies byte 8. Every packet has the existing Sidus checksum and
travels through the shared connection. The old research note's 0x07 off bytes
omitted the setter bit; the implemented base stop is `96000000000000000f87`.

First/second-generation presets follow the effect-layer constructors, with HA
intensity substituted. Complex presets use their default HSI mode. TV, Fire,
and Candle I use `cct_type=0`, not a literal color temperature. Welding II's
minimum intensity is capped at the requested maximum when dimmed.

The SDK has no high-level generation-III preset defaults. Its encoders are
implemented with explicitly chosen test presets: HSI hue 1, saturation 100,
5600 K white point; frequency 5; gap values 20/60; TV/Fire hue range 1..180;
Cop car palette 2. These values reuse the earlier preset conventions. Their
appearance and timing require hardware validation; they are not claimed to
match Desktop's defaults.

Paparazzi II, Welding II, and Lightning/TV/Fire/Faulty bulb III use two packets:
parameters/intensity with state 3, then color with state 1. Gen III uses the same
staging convention as the corresponding Gen II layout; validate that sequence
on hardware. Stops use state 0 in the same effect family. First-generation
stops use effect 15.

The SDK's `LightMode.FIREWORKS_II` enum disagrees with its dispatcher and protocol
class. The implementation uses protocol/dispatcher effect ID **11**.

| Preset | Desktop flag | Command type | Effect ID |
| --- | --- | --- | --- |
| Club lights | `club_lights` | `0x07` | 0 |
| Paparazzi | `paparazzi` | `0x07` | 1 |
| Lightning | `lightning` | `0x07` | 2 |
| TV | `tv` | `0x07` | 3 |
| Candle | `candle` | `0x07` | 4 |
| Fire | `fire` | `0x07` | 5 |
| Strobe | `strobe` | `0x07` | 6 |
| Explosion | `explosion` | `0x07` | 7 |
| Faulty bulb | `faulty_bulb` | `0x07` | 8 |
| Pulsing | `pulsing` | `0x07` | 9 |
| Welding | `welding` | `0x07` | 10 |
| Cop car | `cop_car` | `0x07` | 11 |
| Color chase | `color_chase` | `0x07` | 12 |
| Party lights | `party_lights` | `0x07` | 13 |
| Fireworks | `fireworks` | `0x07` | 14 |
| Paparazzi II | `paparazzi_2` | `0x22` | 0 |
| Lightning II | `lightning_2` | `0x22` | 1 |
| TV II | `tv_2` | `0x22` | 2 |
| Fire II | `fire_2` | `0x22` | 3 |
| Strobe II | `strobe_2` | `0x22` | 4 |
| Explosion II | `explosion_2` | `0x22` | 5 |
| Faulty bulb II | `faulty_bulb_2` | `0x22` | 6 |
| Pulsing II | `pulsing_2` | `0x22` | 7 |
| Welding II | `welding_2` | `0x22` | 8 |
| Cop car II | `cop_car_2` | `0x22` | 9 |
| Party lights II | `party_lights_2` | `0x22` | 10 |
| Fireworks II | `fireworks_2` | `0x22` | 11 |
| Lightning III | `lightning_3` | `0x22` | 12 |
| TV III | `tv_3` | `0x22` | 13 |
| Fire III | `fire_3` | `0x22` | 14 |
| Faulty bulb III | `faulty_bulb_3` | `0x22` | 15 |
| Pulsing III | `pulsing_3` | `0x22` | 16 |
| Cop car III | `cop_car_3` | `0x22` | 17 |

## Readback and validation

The device-page chooser was validated on Ace 25c and T4c on 2026-09-22:
Fire and return to steady CCT both received confirming device reports; power-off
updated the chooser to `off`, and choosing `off` again did not wake either light.
The Ace UI displayed its 12 presets plus `off`. Core restart sent no controls.

Single-packet effect reports update the selected effect, power, and brightness.
An effect-off report clears the effect without inventing a power or brightness
value and leaves plain-color state assumed until a normal status report arrives.
Multipart effect reports remain assumed because one frame cannot confirm both
the staged intensity and active color. Unsupported color-mode variants also
remain assumed. No synthetic confirmation is produced.

Unit checks cover every preset's packet structure, brightness placement,
stop behavior, capability filtering, restoration, mode transitions, and packet
integrity. Generation II/III packets also match independently compiled Java
SDK output byte for byte. These checks are not physical captures.

On 2026-09-22, the T4c confirmed all 15 first-generation presets through fresh
device reports at 5% intensity. Each preset's reported selection and intensity
matched the request. These checks confirm device settings; the visual appearance
of every effect was not separately judged. No T4c-specific encoder changes were
needed. Dimming preserved the selected Fire preset, and explicit effect-off
returned to CCT with a confirmed report. Repeated effect-off/HSI wake requests
and a cached Fire-to-HSI wake also passed after removing the redundant stop
while off. Generation II/III effects still require hardware validation.

The same day, all 12 effects shared by Ace 25c and T4c were compared at 5%
intensity. Every pair used byte-for-byte identical Sidus packets from this
single encoder, and both lights returned the requested selection and intensity.
The user also confirmed effects were visible on both. Ace effect dimming and
effect-off to CCT passed. The differences are catalog eligibility (12 Ace versus
15 T4c presets), not separate model-specific effect code. Random timing and
physical appearance were not required to match exactly.
