# Plan 014: Spike — design system-effects (FX) support, gated on a real-light capture

> **Executor instructions**: This is a **research / design spike**, not a build.
> Its deliverable is a written design + a decision record, plus (optionally) a
> small set of dormant, clearly-labelled-speculative encoder functions with unit
> tests. **You must not wire effects into the light entity or send any effect
> command to a real light in this plan.** Honor every STOP condition. When done,
> update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 49d7685..HEAD -- docs/protocol.md custom_components/amaran/protocol.py custom_components/amaran/product.json`
> If `docs/protocol.md` changed, re-read its "Effects & extended commands"
> section before proceeding.

## Status

- **Priority**: P3
- **Effort**: M (design-heavy; no shipped feature)
- **Risk**: LOW (docs + optional dormant code; nothing user-visible ships)
- **Depends on**: none
- **Category**: direction (feature research)
- **Planned at**: commit `49d7685`, 2026-06-20

## Why this matters

Built-in lighting effects (candle, lightning, TV, paparazzi, fireworks, …) are
the biggest visible gap between this integration and the official Amaran app.
Spike 005 already mapped the effect protocol generations from the APK and
**deliberately stopped** before building, because the bytes need a per-model
evidence base and a physical-light capture (`docs/protocol.md:198-239`,
especially lines 236-239). This spike turns that research into a concrete,
reviewable **design + decision gate** so a later build plan can execute safely —
and produces an honest go/no-go instead of shipping speculative command bytes.

The output is the product, exactly as in spike 005 (which added only
documentation). Do not let this become a build.

## Current state (what is already known)

`docs/protocol.md:198-239` "Effects & extended commands" records:

- Three effect protocol generations: first-gen command type `0x07` (e.g. Candle
  effect type `0x04`, then CCT bits `40..49`, frequency bits `50..53`, intensity
  bits `54..63`), `0x21`, and second-gen `0x22`/`34` (e.g. Lightning II effect
  type `0x01` with state/intensity/frequency/speed/mode and mode-dependent
  CCT·G/M or HSI fields). Effect-off is command type `0x07`, effect type `0x0f`.
- APK source citations (in `artifacts/jadx/sources/com/sidus/link/...`):
  `CandleProtocol.java:15-63`, `LightningProtocol2.java:20-97`,
  `SystemEffectPacker.java:96-205` and `:207-294`, `EffectOffProtocol.java:9-41`,
  plus the dispatch in `DataPacker.java`.
- Per-model support is a subset of `systemfx_*` flags; the app marks only some
  models. `amaran-cli` exposes `get_system_effect_list`/`set_system_effect`
  **per node**, confirming effect lists are per-model, not global.
- HA modeling guidance (`docs/protocol.md:224-228`): expose only a model's
  verified effects via `effect_list`, accept `ATTR_EFFECT` in `async_turn_on`,
  report `EFFECT_OFF` when none active, use an effect-appropriate color mode,
  per the HA light entity contract.

Relevant code facts for the design:

- The 10-byte Sidus payload and its checksum helper are in `protocol.py`
  (`sidus_checksum` at `:83`, `_finalize_sidus` at `:91`, e.g. `cct_payload`
  packs an 80-bit little-endian value at `:138-169`). Any effect encoder reuses
  `_finalize_sidus`.
- `product.json` is a **vendored, byte-identical mirror** of amaran Desktop's
  catalog (run-1 plan 003 confirmed it byte-identical; its rows are only
  `id, name, hex, authorized_amaran, icon_url_amaran, public_version` — no
  capability or effect fields). **Do not add effect fields to `product.json`** —
  it must stay refreshable from Desktop without conflict. Per-model effect data
  belongs in a separate side-table.
- Capability classification today is name/code/id based in `product_catalog.py`
  (`classify_product_name`, `lookup_product`) and `fixtures.py`. The effect
  side-table should key on the same identity (`hex` code and/or product `id`)
  so it can join to `lookup_product`.

Prerequisite for any byte-level work: the jadx-decompiled sources cited above
live under `artifacts/` (gitignored) and may not be present. The bundled APK is
at `artifacts/apk/amaran-base.apk`. If you need to verify a byte layout beyond
what `docs/protocol.md` already states, decompile that APK with `jadx`; if you
cannot, rely only on the layouts already written in `docs/protocol.md` and mark
anything beyond them as unverified.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Full suite | `python3 -m unittest discover -s tests` | last line `OK` |
| Protocol tests (if Phase B) | `python3 -m unittest tests.test_protocol -v` | `OK` |
| (Optional) decompile APK | `jadx -d artifacts/jadx artifacts/apk/amaran-base.apk` | sources under `artifacts/jadx/sources/` |

**Do not use `pytest`** (intercepted). Use `unittest`.

## Scope

**In scope**:
- `docs/effects-design.md` (create) — the design + decision record.
- `docs/protocol.md` — optionally add a back-link to the new design doc.
- **Phase B only, optional**: `custom_components/amaran/protocol.py` (add dormant
  encoder functions) and `tests/test_protocol.py` (structural tests for them).

**Out of scope** (do NOT touch):
- `light.py`, `client.py`, `commands.py`, `services.yaml`, `strings.json`,
  `__init__.py` — no effect is wired to an entity, service, or transport in this
  spike.
- `product.json` — never add effect fields to the vendored catalog.
- Sending any effect command to a real light.

## Deliverable 1 (required): `docs/effects-design.md`

Write a design document with these sections:

1. **Target scope** — which effects to support first and why. Recommend starting
   with the **first-generation system effects (command type `0x07`)** on the two
   models with the strongest evidence (Ace 25c `400U5`, Pano 60c `400W5`), plus
   **effect-off** (`0x07`/`0x0f`). Defer second-gen `0x22` until first-gen is
   validated.
2. **Byte layout** — for each targeted effect, the exact 10-byte payload layout,
   transcribed from `docs/protocol.md` (and the cited APK classes if you
   decompiled). Mark every field "documented" vs "inferred". Note checksum is
   `sidus_checksum` / byte 0.
3. **Per-model effect side-table** — design a data file
   `custom_components/amaran/product_effects.json` (or an in-module table in
   `product_catalog.py`) keyed by product `hex` code and/or `id`, mapping each
   supported model to its ordered `effect_list` of HA-facing effect names and the
   encoder parameters each needs. Show the proposed JSON shape with one worked
   example row for Ace 25c. State explicitly that a model **absent** from the
   table exposes **no** effects (conservative default).
4. **Home Assistant modeling** — how the light entity will expose effects:
   `LightEntityFeature.EFFECT`, `effect_list` from the side-table, `ATTR_EFFECT`
   handling in `async_turn_on`, `EFFECT_OFF` semantics, and which `ColorMode` an
   active effect reports. Tie each choice to the HA light entity contract
   referenced in `docs/protocol.md:228`.
5. **Capture & validation procedure** — the exact steps to validate bytes on a
   real Ace/Pano before any build ships: trigger the effect in the official app,
   capture the decrypted Mesh Proxy Data In write (reusing the existing diagnostic
   path — the `request_power_status` service already logs decrypted Mesh Proxy
   Data Out, `services.yaml:1-26`), compare to the documented layout, and record
   the captured hex. State that the build plan is **blocked** until at least one
   effect round-trips on hardware.
6. **Decision record (go/no-go)** — a short table: per targeted effect, evidence
   strength (documented/inferred/captured), and a recommendation
   (build now / needs capture / defer). Be honest: with no capture in-repo, the
   expected recommendation is "design ready, build gated on capture."
7. **Follow-up build plan outline** — bullet the steps a future build plan (e.g.
   `plans/0NN-effects-build.md`) will take once a capture validates: encoder(s) in
   `protocol.py`, command builders in `commands.py`, client method, side-table
   load + `effect_list` wiring in `light.py`, tests, physical validation.

**Verify**: `test -f docs/effects-design.md && wc -l docs/effects-design.md`
shows a non-trivial document; all seven sections present
(`grep -nE "^## " docs/effects-design.md` lists them).

## Deliverable 2 (OPTIONAL — only if the operator wants dormant encoders now)

Spike 005 shipped **no** code by design. Only do this phase if the operator
explicitly asks for tested-but-dormant encoders. If you do:

- Add to `protocol.py`, beside the other payload builders, speculative encoders
  for the first-gen candle and effect-off payloads, e.g.:
  ```python
  def system_effect_off_payload() -> bytes:
      """SPECULATIVE (hardware-unvalidated): first-gen effect-off, type 0x07/0x0f.

      Layout per docs/protocol.md 'Effects & extended commands'. Not wired to any
      entity; do not use to drive a real light until validated by capture.
      """
      payload = bytearray(10)
      payload[8] = 0x0F  # effect type
      payload[9] = 0x07  # command type
      return _finalize_sidus(payload)
  ```
  (Confirm the byte positions against `docs/protocol.md` before committing; adjust
  the docstring to match exactly what the doc states.)
- Add **structural** tests to `tests/test_protocol.py` (model on `class
  StatusPayloadTest`): assert command-type byte == `0x07`, effect-type byte as
  documented, and `payload[0] == sidus_checksum(payload)`. **Do not** assert
  parity against any capture — none exists; say so in a comment.
- Keep every encoder unreferenced by entities/transport (dormant).

**Verify**: `python3 -m unittest tests.test_protocol -v` → `OK`.

## Done criteria

- [ ] `docs/effects-design.md` exists with all seven required sections.
- [ ] The design names a concrete per-model side-table file/shape and states the
      "absent model ⇒ no effects" default.
- [ ] The design contains a go/no-go decision table and a capture procedure.
- [ ] `product.json` is unchanged (`git diff --stat 49d7685..HEAD -- custom_components/amaran/product.json` empty).
- [ ] If Phase B was done: `python3 -m unittest discover -s tests` → `OK`, new
      encoders are dormant (`grep -rn "system_effect_off_payload" custom_components/amaran/`
      shows it only in `protocol.py`).
- [ ] No entity/service/transport file modified.
- [ ] `plans/README.md` status row for 014 updated.

## STOP conditions

Stop and report (do not improvise) if:

- You find yourself editing `light.py`/`client.py`/`commands.py`/`services.yaml`
  to "just wire one effect" — that is the build, not this spike.
- You cannot transcribe a byte layout from `docs/protocol.md` and the jadx
  sources are absent and the APK won't decompile — write the design with the
  documented effects only and flag the rest as needing decompilation.
- The design appears to require changing `product.json` — re-read "Current
  state"; use the side-table instead.

## Maintenance notes

- The hard line preserved here: **no effect command ships without a real-light
  capture.** The design doc must make the next executor's gate unmistakable.
- When the build lands, the per-model side-table is the thing to keep in sync as
  Amaran adds models/effects — note that in the doc.
- Plan 015 (RGBWW) reuses this spike's capture procedure; keep the capture steps
  generic enough to cover both.
