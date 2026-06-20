# Plans

Reconciled 2026-06-20 against HEAD `0a14f9d` (`main`) + **uncommitted** perf work
(016–018) in the working tree. Suite: `python3 -m unittest discover -s tests` →
**178 OK**.

| Plan | Status | Notes |
| --- | --- | --- |
| 012 | DONE (verified) | `012-green-magenta-cct-tint.md` — committed `6f26391`; scope clean, done criteria hold. Physical-light validation still pending before relying on it. |
| 013 | DONE (committed) | `013-multi-light-import.md` — committed `327a2eb` (`feat(amaran): import multiple lights in one pass`). Physical validation that selecting N lights yields N entries still pending. |
| 014 | DONE (verified) | `014-effects-capture-spike.md` — design in `docs/effects-design.md` (7 sections); docs-only, `product.json` untouched. Build gated on real-light capture. |
| 015 | DONE (verified) | `015-rgbww-capture-spike.md` — design in `docs/rgbww-design.md` (7 sections); docs-only, no encoder/entity wiring. Build gated on mixed RGB+white real-light capture. |
| 016 | DONE (verified, uncommitted) | `016-cache-mesh-key-derivation.md` — perf P1. `@lru_cache(maxsize=8)` on `derive_mesh_keys` (`protocol.py:346`), body unchanged; +2 tests (`DeriveMeshKeysCacheTest`). Verified greps + suite. **Working tree only — not committed.** |
| 017 | DONE (verified, uncommitted) | `017-batch-sequence-persistence.md` — perf P2. High-water mark in `SidusSequenceManager` (`client.py:90,109,130,152,164`); +3 tests pinning batch=1-write-per-64 + restart resume. Transport `save_count==2` intact. **Uncommitted; physical-light + restart validation still pending** (mesh sequence durability). |
| 018 | DONE (verified, uncommitted) | `018-guard-hot-path-debug-logging.md` — perf P3. 5 `isEnabledFor` guards in `transport.py` (TX `access` build now guarded at `:603-604`) + 3 in `client.py`; +3 tests (`HotPathLoggingGuardTest`, `RxLoggingGuardTest`). **Working tree only — not committed.** |

Status values: TODO | IN PROGRESS | DONE | BLOCKED | REJECTED

## Reconcile notes (2026-06-20)

- **012** — commit `6f26391` changed only in-scope files (`__init__.py`,
  `client.py`, `commands.py`, `number.py`, `test_client.py`, `test_number.py`,
  `test_protocol.py`). Verified: `number.py` defines `AmaranGreenMagentaNumber`;
  zero `Platform.LIGHT, Platform.SENSOR)` remnants in `__init__.py`; `gm` on all
  three CCT builders in `commands.py`. Suite green.
- **013** — fully implemented but **uncommitted**. `cv.multi_select` present in
  `config_flow.py`; `fixture_entries_for_selection` in `fixtures.py` +
  `config_flow.py`; `test_ux_strings` passes (no "fixture/proxy/transport" leaked
  into `en.json` values). Next action: commit it (own branch) + physical
  validation that selecting N lights yields N entries.
- **014** — pure design spike (matches the 005 precedent: docs, no shipped code).
  No entity/transport/protocol file touched.
- **015** — pure design spike (matches the 014 capture-gated pattern). No
  entity/transport/protocol file touched; dormant encoder skipped because it was
  optional and not requested.

## Direction findings considered and NOT planned

- **Telemetry as entities** (AC-vs-battery `binary_sensor`, runtime-remaining,
  RSSI) — already decoded in `SidusPowerInfo`, only in battery-sensor attributes.
  Additive, effort S. Not selected.
- **Push-sync proving / retire polling** — proxy filter already built
  (`protocol.py:410`); remainder is manual physical validation, folds into the
  `fix/proxy-link-watchdog` work. No plan.

## Run 3 (2026-06-20): performance focus

`/improve performance` (standard) against HEAD `0a14f9d`; baseline `python3 -m
unittest discover -s tests` → **170 OK**. Audited the perf category directly (read
all hot-path files: `transport.py`, `client.py`, `protocol.py`, `const.py`,
`__init__.py`).

**Recommended order**: 016 → 017 → 018. All three are **independent** (no plan
depends on another) and may land in any order or in parallel; 016 first because
it is the highest-leverage and smallest. 018 notes that 016 removes the dominant
RX cost, so 018 is most worthwhile after 016.

**Performance findings considered and NOT planned:**

- **`SidusTransportMetrics.as_dict()` + `_last_write` rebuilt every TX write**
  (`transport.py:658-673`) — ~40 dict keys allocated per write for diagnostics
  read rarely. TX-only (not the per-packet RX path), small magnitude. Skipped —
  low leverage and `_last_write`/`metrics` are part of the diagnostics contract.
- **N independent pollers serialize on one transport without staggering**
  (`client.py:877-928`) — real at multi-light scale, but each light needs its own
  per-node status request (can't dedupe) and the fix is a `DataUpdateCoordinator`
  refactor. AGENTS.md forbids transport-path changes without physical-light
  validation, so this is deferred as an architecture spike, not a perf quick-win.
  017 removes the worst per-poll cost (the disk write) regardless.
- **`_matching_mesh_context` O(N²) `mesh_network_key` (sha256) at startup**
  (`__init__.py:407-432`) — startup-only, tiny inputs; negligible. Not a finding.
- **`product_catalog()`** is already `@lru_cache`'d (`product_catalog.py:46`) and
  loaded via executor at setup (`__init__.py:144-146`) — correct as-is.

### Run 3 reconcile (2026-06-20)

All three perf plans were executed **into the working tree** (HEAD unchanged at
`0a14f9d`; `git status` shows `M` on the six in-scope source/test files; plan
files 016–018 untracked). Verified:

- **Scope clean** — modified files are exactly the union of the three plans'
  in-scope sets; no out-of-scope source touched.
- **Done criteria hold** — all machine-checkable greps pass (see row notes);
  full suite **178 OK** (170 baseline + 8 new: 016→2, 017→3, 018→3).
- **Tests are real, not gamed** — `017` `test_skips_disk_writes_until_high_water_is_exceeded`
  (1 write across 64 sends) and `018` `RxLoggingGuardTest` (`debug.assert_not_called`)
  both fail if the feature is absent; `016` uses `assertIs` on the cached instance.
- **Substance spot-checks** — `derive_mesh_keys` body byte-identical under the
  decorator; TX `access = access_payload(...)` correctly moved inside the
  `isEnabledFor` guard while the real `build_mesh_proxy_pdu(...)` stays outside.

**Outstanding before relying on this work:**

1. **Commit it.** Nothing is committed; a HA restart or `git checkout` loses all
   three. Suggest one branch + a commit per plan (conventional-commit messages
   are in each plan's Git workflow section).
2. **Physical-light validation for 017** (AGENTS mandate — mesh sequence
   durability): run several commands on a real light, restart Home Assistant,
   confirm commands still take effect and no sequence-reuse rejection. 016 and 018
   are pure (cache / logging) and need no light validation.

## Prior runs (history, not in this tree)

Plans 001–011 ran on `advisor/*` branches (run 1: 001–005 full-color + status
spike → v0.4.0–0.4.6; run 2: 006–011 CI, thread-safety, perf, dead-code).
Settled, do not re-audit: Verge/Go/Verge Max are CCT-only (regression-tested);
light `should_poll=True` is required not redundant; protocol/crypto packing is
parity-locked to the reference implementation.
