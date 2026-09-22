# Audit Fixes Implementation Plan

**Status:** Implemented and deployed to Home Assistant 2026.9.2. T4c HSI is visually confirmed; CCT, tint, brightness, and all 15 base effects have fresh device readback. Additional-model validation remains pending.
**Goal:** Correct packet validation, tint encoding, startup state, and per-light cleanup found in the repository audit.

**Architecture:** Keep the shared mesh transport. Dispose per-light subscriptions independently of the network reference count. Preserve cached light values while requiring fresh reports to confirm them.

**Tech Stack:** Python, Home Assistant, cryptography, unittest.

**Spec:** User request dated 2026-09-22 and `AGENTS.md`.

## Global Constraints

No startup control commands, no Bluetooth discovery, one entry per light, one shared mesh connection. Preserve unrelated changes. User authorized implementation; physical validation follows after Desktop releases Bluetooth.

### Task 1: Packet correctness

**Files:** Modify `custom_components/amaran/protocol.py`; test `tests/test_protocol.py`.

**Interfaces:** `cct_payload_percent(gm=...)` retains signed integer offsets; `decode_mesh_proxy_access(...)` returns `None` for failed authentication.

- [x] Add signed tint bit-field checks for -10, -5, -1, 0, 5, 10 and malformed/authentication-failure packet checks.
- [x] Round signed inputs correctly and catch `InvalidTag` at both authentication boundaries.
- [x] Run the focused command again; expect PASS.

### Task 2: Entry and entity lifecycle

**Files:** Modify `custom_components/amaran/client.py`, `custom_components/amaran/__init__.py`, `custom_components/amaran/light.py`; test `tests/test_client.py`, `tests/test_light.py`.

**Interfaces:** Synchronous per-client cleanup cancels subscriptions without closing another entry's mesh. Restore always starts assumed, and unsupported reported/restored modes are normalized to supported modes.

- [x] Add checks for entry unload cancelling polling without closing a shared mesh and restoring a previously confirmed snapshot as assumed.
- [x] Wire per-client cleanup into unload, retain shared network release, and normalize restored/reported state.
- [x] Repeat the focused commands; expect PASS.

### Task 3: Integration verification and documentation

**Files:** Modify `docs/protocol.md`, `CHANGELOG.md`; verify `.github/workflows/ci.yml` checks.

**Interfaces:** Documentation describes current proxy filtering, polling, and validation limits.

- [x] Replace obsolete receive-path claims with current behavior and physical-validation boundaries.
- [x] Run `python3 -m unittest discover -s tests` and `uvx --from ruff==0.15.18 ruff check .`; expect PASS.
- [x] Review the final diff and preserve a clean distinction between unit verification and physical-light validation.

Product identification/export and HSI/CCT+/RGB/effects work is tracked separately in the color-capability plan.

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
