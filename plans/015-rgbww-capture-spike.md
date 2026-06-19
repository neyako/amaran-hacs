# Plan 015: Spike — design RGBWW full-color support, gated on a real-light capture

> **Executor instructions**: This is a **research / design spike**, not a build.
> Deliverable is a written design + decision record, plus (optionally) one
> dormant, clearly-labelled-speculative encoder with structural tests. **Do not
> wire RGBWW into the light entity or send any RGBWW command to a real light.**
> Honor every STOP condition. When done, update the status row in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 49d7685..HEAD -- docs/protocol.md custom_components/amaran/light.py custom_components/amaran/protocol.py`
> If `docs/protocol.md` changed, re-read its "Effects & extended commands"
> section first.

## Status

- **Priority**: P3
- **Effort**: S–M (design-heavy)
- **Risk**: LOW (docs + optional dormant code)
- **Depends on**: `plans/014-effects-capture-spike.md` (reuses its capture
  procedure; can also be done standalone if 014 is skipped)
- **Category**: direction (feature research)
- **Planned at**: commit `49d7685`, 2026-06-20

## Why this matters

Color-capable Amaran lights (Ace 25c, Pano 60c) expose **independent warm and
cool white channels alongside RGB** (RGBWW). Today the integration models them as
HS only (`light.py:87` adds `ColorMode.HS`), which collapses the two white
channels — you cannot, for example, mix a warm-white base with a colored accent.
Spike 005 mapped the RGBWW command but **deferred** it because the bytes need a
physical capture to confirm whether simultaneous RGB + white values are accepted
(`docs/protocol.md:204,229-234`). This spike produces the design + decision gate
so a later build can map `ColorMode.RGBWW` safely.

Marginal value is lower than effects (HS already "sets a color"), so this is
explicitly secondary — but the capture session is shared with plan 014, making it
cheap to design alongside.

## Current state (what is already known)

`docs/protocol.md:204` and `:229-234` record:

- RGBWW is **command type `0x04`, setter byte 9 = `0x84`**. Channels are 10-bit:
  intensity bits `12..21`, cool white `22..31`, warm white `32..41`, blue
  `42..51`, green `52..61`, red `62..71`. Source: `RGBWProtocol.java:22-79`,
  dispatch `DataPacker.java:55-59`. Confidence: "High for byte layout; low for
  supported simultaneous-white behavior."
- Only Ace 25c (`400U5`) and Pano 60c (`400W5`) carry `rgb_support=1` in the app
  config — it does **not** establish that warm/cool white may be mixed with RGB.
- HA modeling guidance (`docs/protocol.md:229-234`): model the five channels as
  `ColorMode.RGBWW` / `rgbww_color`, **not** HS (HS cannot preserve independent
  warm + cool white). Explicit warning: *"Do not add RGBWW from the Java class
  alone; first capture a command from a supported Ace/Pano and record channel
  scaling and whether simultaneous nonzero RGB + white values are accepted."*

Relevant code facts:

- Current color-mode wiring: `light.py:82-90` builds
  `_attr_supported_color_modes` from the client's `supported_color_modes` /
  `supports_hs`. The HSI send path is `client.async_set_hsi` (`client.py:1112`)
  and `protocol.hsi_payload` (`protocol.py:189`). RGBWW would be a **new** mode
  and command, not a change to HSI.
- The 10-byte packing + checksum helpers (`sidus_checksum`, `_finalize_sidus`,
  the little-endian bit-pack style in `cct_payload`) are in `protocol.py` and any
  RGBWW encoder reuses them.
- HA's `ColorMode.RGBWW` uses `rgbww_color` as a 5-tuple `(r, g, b, cw, ww)` each
  `0..255`; the design must define the mapping to the device's 10-bit `0..1000`
  (or `0..1023`) channel scale — that scaling is one of the things the capture
  must confirm.
- Per the capability rules (`AGENTS.md` "Capability Mapping"), only Ace 25c and
  Pano 60c are RGB-capable; RGBWW must be gated to those models, not applied to
  CCT-only lights.

Prerequisite for byte-level verification beyond the documented layout: the jadx
sources are under gitignored `artifacts/`; the APK is at
`artifacts/apk/amaran-base.apk` (decompile with `jadx` if needed). Otherwise rely
on the layout already in `docs/protocol.md`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Full suite | `python3 -m unittest discover -s tests` | last line `OK` |
| Protocol tests (if Phase B) | `python3 -m unittest tests.test_protocol -v` | `OK` |

**Do not use `pytest`** (intercepted). Use `unittest`.

## Scope

**In scope**:
- `docs/rgbww-design.md` (create) — design + decision record.
- **Phase B only, optional**: `custom_components/amaran/protocol.py` (one dormant
  encoder) + `tests/test_protocol.py` (structural test).

**Out of scope** (do NOT touch):
- `light.py`, `client.py`, `commands.py`, `fixtures.py`, `product.json`,
  `product_catalog.py` — no RGBWW is wired to an entity or to capability
  detection in this spike.
- The HSI path — RGBWW is additive, not a modification of HS.
- Sending any RGBWW command to a real light.

## Deliverable 1 (required): `docs/rgbww-design.md`

Write a design document with these sections:

1. **Byte layout** — the 10-byte RGBWW payload (`0x84`) with all six fields
   (intensity + 5 channels) transcribed from `docs/protocol.md:204`. Mark each
   field documented vs inferred. Note the checksum byte.
2. **Open questions the capture must answer** — at minimum: (a) are simultaneous
   nonzero RGB **and** white channels accepted, or does the device clamp/ignore
   one set? (b) channel scale — `0..1000` (like intensity) or `0..1023` (full
   10-bit)? (c) does setting RGBWW imply power-on like the other setters? List
   each as a yes/no or value-to-record item.
3. **HA modeling** — map `ColorMode.RGBWW` / `rgbww_color` `(r,g,b,cw,ww)` to the
   device channels, including the `0..255` → device-scale conversion and rounding
   (mirror the existing `_ha_brightness_to_intensity` style in `protocol.py:104`).
   Specify how `RGBWW` coexists with the light's existing `BRIGHTNESS`/`COLOR_TEMP`
   modes in `_attr_supported_color_modes` and which mode is reported when.
   Per HA rules, when `RGBWW` is supported the entity generally should **not**
   also advertise `HS` (RGBWW supersedes it) — analyze and recommend.
4. **Model gating** — RGBWW only for Ace 25c / Pano 60c. Specify how the build
   will detect that (reuse `lookup_product` by `hex` `400U5`/`400W5`, or a
   capability flag), consistent with `AGENTS.md` capability mapping.
5. **Capture & validation procedure** — reuse plan 014's capture path
   (`docs/effects-design.md` if it exists; otherwise describe it here): trigger an
   RGBWW state in the official app on a real Ace/Pano, capture the decrypted Mesh
   Proxy Data In write, and record the hex for at least three cases — pure RGB,
   pure white, and mixed RGB+white — to answer the open questions in section 2.
6. **Decision record (go/no-go)** — recommendation given current evidence.
   Expected honest outcome: layout documented, **build blocked on capture** of the
   mixed-channel case.
7. **Follow-up build plan outline** — the steps a future build plan will take:
   `rgbww_payload` encoder in `protocol.py`, builder in `commands.py`, client
   `async_set_rgbww`, `light.py` mode wiring gated to Ace/Pano, tests, physical
   validation.

**Verify**: `test -f docs/rgbww-design.md` and
`grep -nE "^## " docs/rgbww-design.md` lists all seven sections.

## Deliverable 2 (OPTIONAL — only if the operator wants a dormant encoder now)

Only if explicitly requested. If you do:

- Add a speculative `rgbww_payload(*, red, green, blue, cool_white, warm_white,
  intensity)` to `protocol.py` packing the documented `0x84` layout with
  `_finalize_sidus`, docstring clearly marked **SPECULATIVE / hardware-unvalidated
  / dormant**.
- Add a **structural** test to `tests/test_protocol.py`: command-type byte ==
  `0x84`, a single-channel round-trips into the expected bit range, and
  `payload[0] == sidus_checksum(payload)`. **No** capture-parity assertion (none
  exists) — comment why.
- Keep it unreferenced by any entity/transport.

**Verify**: `python3 -m unittest tests.test_protocol -v` → `OK`.

## Done criteria

- [ ] `docs/rgbww-design.md` exists with all seven sections.
- [ ] The design lists the explicit open questions the capture must answer
      (simultaneous RGB+white, channel scale, implied power-on).
- [ ] The design gates RGBWW to Ace 25c / Pano 60c only.
- [ ] If Phase B done: `python3 -m unittest discover -s tests` → `OK`; encoder is
      dormant (`grep -rn "rgbww_payload" custom_components/amaran/` shows it only in
      `protocol.py`).
- [ ] No entity/capability/transport file modified; `product.json` unchanged.
- [ ] `plans/README.md` status row for 015 updated.

## STOP conditions

Stop and report (do not improvise) if:

- You start editing `light.py`/`client.py`/`commands.py`/`fixtures.py` to wire
  RGBWW — that is the build, not this spike.
- The documented layout in `docs/protocol.md` is insufficient and the APK won't
  decompile — write the design from the documented layout and flag the gaps.
- The design seems to require advertising `RGBWW` for CCT-only models — re-read
  "Model gating"; gate to Ace/Pano.

## Maintenance notes

- The `docs/protocol.md:234` warning is the crux: **never ship RGBWW from the
  Java layout alone** — the mixed RGB+white capture is mandatory. The design doc
  must make that gate unmistakable to the build executor.
- If RGBWW supersedes HS for Ace/Pano, the build will change those lights'
  advertised color modes — call out the migration/UX impact (existing automations
  using `hs_color` on those lights) in the design's decision section.
- Shares plan 014's capture session; coordinate so one hardware session collects
  both effect and RGBWW captures.
