# Desktop Color Capabilities Implementation Plan

**Status:** Implemented and deployed to Home Assistant 2026.9.2. T4c HSI is visually confirmed; CCT, tint, brightness, and all 15 base effects have fresh device readback. Additional-model validation remains pending.
**Goal:** Refresh all Desktop products, enable basic HSI from explicit metadata, preserve export identity, and expose model-specific CCT+ ranges.

**Architecture:** Keep `product.json` as the Desktop product mirror and join a compact `product_capabilities.json` snapshot by product code. Existing command transport remains shared. Product metadata controls HSI, CCT ranges, RGB, tint, and effect eligibility; command implementations remain responsible for the supported wire format.

**Tech Stack:** Python stdlib JSON/SQLite, Home Assistant light entities, existing unittest checks.

**Spec:** User request dated 2026-09-22; installed Amaran Desktop 1.1.03 (129) Resources/config catalogs.

## Global Constraints

User authorizes enabling HSI on catalog-supported models for physical validation, superseding the old Ray-only restriction. The test model remained undisclosed during implementation. The user subsequently selected T4c and authorized its Desktop export for validation. No startup writes, discovery, or extra connections per mesh. Exported credentials remain private. Use native Home Assistant controls; no custom frontend is needed. Basic HSI is distinct from RGB and advanced HSI. Effects require a known encoder as well as a capability flag.

### Task 1: Authoritative catalog

**Files:** Modify `custom_components/amaran/product.json`, `custom_components/amaran/product_catalog.py`, `tests/test_fixtures.py`; create `custom_components/amaran/product_capabilities.json`.

**Interfaces:** `Product.color_modes` derives from `hsi_support` and `cct_support`; `Product` exposes standard/extended Kelvin bounds and RGB/tint metadata. Source provenance records Desktop version. Non-light products cannot create light entities.

- [x] Replace Ray-restriction tests with ID/code recognition and HSI flag tests; cover HSI-without-RGB, bi-color, cameras/audio, and CCT+ ranges.
- [x] Refresh all 98 product rows and normalize relevant flags from 99 config profiles, requiring equal relevant fields across hardware variants.
- [x] Join by code, use explicit flags for known profiles, and retain conservative legacy name fallback only where metadata is absent.
- [x] Repeat focused tests; expect PASS.

### Task 2: Stable export identity

**Files:** Modify `scripts/export_amaran.py`, `tests/test_export_amaran.py`.

**Interfaces:** Export records retain `code` and `product_id`, capabilities and catalog flags. Current local Desktop metadata takes precedence when available; bundled/downloaded catalog supports standalone export elsewhere.

- [x] Test a custom-named light using product ID/code and an unknown product retaining both identifiers.
- [x] Preserve identifiers and use metadata instead of the duplicated Ray exclusion; reject camera/audio/accessories.
- [x] Repeat focused tests; expect PASS.

### Task 3: CCT+ and capability propagation

**Files:** Modify `custom_components/amaran/client.py`, `custom_components/amaran/light.py`, `custom_components/amaran/state.py`, `custom_components/amaran/number.py`; test their existing test modules and `tests/test_protocol.py`.

**Interfaces:** Per-model min/max Kelvin flows through HA attributes, planner, client clamping and restore. CCT+ uses the existing 0x82 range bit for 1800..20000 K where advertised. Tint entities follow `gm_support`.

- [x] Add CCT+ range/packet checks and an out-of-range clamp check on a bi-color light.
- [x] Pass model bounds through the existing command and state path; retain last values at restart without commands.
- [x] Run full unittest and pinned Ruff checks; expect PASS.

### Task 4: Documentation and validation

**Files:** Modify `README.md`, `AGENTS.md`, `CHANGELOG.md`, `docs/protocol.md`.

**Interfaces:** Document Desktop-derived support separately from physical validation; raw mesh details remain diagnostics-only.

- [x] Remove obsolete Ray name-only and no-HSI statements, record metadata provenance and export upgrade guidance.
- [x] Validate the previously undisclosed T4c after the user selected it and released Desktop control; keep other-model checks explicit.

RGB and all 33 system-effect codecs are implemented; SDK provenance and remaining physical checks are recorded in the RGB/effects plan and docs/effects-design.md.

## Verification

- `python3 -m unittest discover -s tests`: 213 tests pass.
- `uvx --from ruff==0.15.18 ruff check .`: pass.
- `git diff --check`: pass.
- [x] Import T4c through the normal Desktop JSON flow and visually confirm HSI red/green/blue/off.
- [x] Confirm power, saturation, dimming, 2500–7500 K CCT, signed tint, and all 15 base effects through device reports.
- [x] Fix and confirm repeated effect-off/HSI wake requests, including a cached Fire effect.
- [x] Confirm Core restart preserves off state and entry reload reconnects/restores HSI, both without startup control commands.
- [x] Compare all 12 shared Ace/T4c effects using identical packets, matching reports, and user visual confirmation.
- [x] Confirm Ace 2300–10000 K CCT, signed tint, and effect dimming.
- [x] Fix truncated Ace RGB replies overwriting the requested color with black; keep incomplete color state assumed.
- [ ] Validate accurate native RGB color readback, 1800–20000 K extended CCT, and generation II/III effects; neither tested light advertises the extended CCT/effect generations.
