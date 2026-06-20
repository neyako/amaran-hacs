# Plans

Reconciled 2026-06-20 against HEAD `2193a35` (`main`). Plans 012–018 are all
committed (perf 016–018 landed in `bea84f7`); plans 019–022 are implemented in
the working tree. Suite: `uvx --with cryptography python -m unittest discover -s
tests` → **188 OK**.

| Plan | Status | Notes |
| --- | --- | --- |
| 012 | DONE (verified) | `012-green-magenta-cct-tint.md` — committed `6f26391`; scope clean, done criteria hold. Physical-light validation still pending before relying on it. |
| 013 | DONE (committed) | `013-multi-light-import.md` — committed `327a2eb` (`feat(amaran): import multiple lights in one pass`). Physical validation that selecting N lights yields N entries still pending. |
| 014 | DONE (verified) | `014-effects-capture-spike.md` — design in `docs/effects-design.md` (7 sections); docs-only, `product.json` untouched. Build gated on real-light capture. |
| 015 | DONE (verified) | `015-rgbww-capture-spike.md` — design in `docs/rgbww-design.md` (7 sections); docs-only, no encoder/entity wiring. Build gated on mixed RGB+white real-light capture. |
| 016 | DONE (committed `bea84f7`) | `016-cache-mesh-key-derivation.md` — perf P1. `@lru_cache(maxsize=8)` on `derive_mesh_keys` (`protocol.py:346`), body unchanged; +2 tests (`DeriveMeshKeysCacheTest`). |
| 017 | DONE (committed `bea84f7`) | `017-batch-sequence-persistence.md` — perf P2. High-water mark in `SidusSequenceManager` (`client.py:90,109,130,152,164`); +3 tests pinning batch=1-write-per-64 + restart resume. Physical-light + restart validation still pending (mesh sequence durability). |
| 018 | DONE (committed `bea84f7`) | `018-guard-hot-path-debug-logging.md` — perf P3. 5 `isEnabledFor` guards in `transport.py` (TX `access` build guarded at `:603-604`) + 3 in `client.py`; +3 tests (`HotPathLoggingGuardTest`, `RxLoggingGuardTest`). |
| 019 | DONE (verified) | `019-test-diagnostics-redaction.md` — tests/security. `tests/test_diagnostics.py` locks the diagnostics key-redaction contract (top-level + nested-fixture keys redacted; raw key hex absent from full output; runtime section key-free). Regression guard, no source change. +3 tests. |
| 020 | DONE (verified) | `020-test-state-store.md` — tests. `tests/test_state_store.py` pins `_state_store_key` (sha1 identity formula + differentiators) and the save/load round-trip shape. Guards against silently orphaning persisted light state. +7 tests. |
| 021 | DONE (verified) | `021-make-ruff-ci-blocking.md` — dx. Dropped `continue-on-error` from the `lint` job and pinned `ruff==0.15.18`; closes the advisor-006 TODO. CI-only. |
| 022 | DONE (verified) | `022-telemetry-entities-spike.md` — direction spike. `docs/telemetry-design.md` designs power-source `binary_sensor` + runtime/voltage sensors from already-decoded `SidusPowerInfo`; optional dormant helpers skipped. GO/no-go: **buildable now** (no hardware gate). |

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

## Run 4 (2026-06-20): deep audit (all categories)

`/improve deep` against HEAD `2193a35`; baseline `python3 -m unittest discover -s
tests` → **178 OK**; `uvx ruff check .` → **All checks passed**. Audited directly
(not via subagents): the repo is small and already thrice-audited, so context-blind
fan-out would mostly re-surface the settled ledger below. Read all 18 source
modules + recon/config.

**Verdict**: codebase is mature and clean — crypto parity-locked + tested, security
model solid (recursive redaction + diagnostics double-redact; no live key leak
found), transport/watchdog sound, 178 tests. Prior runs took the high-leverage
wins; what remained were regression-guard test gaps and one CI tidy, not bugs.

**Recommended order**: 019 → 020 → 021 → 022. All four are **independent** (no plan
depends on another). 019 + 020 are the highest value (lock the security-critical
diagnostics redaction and the persisted-state identity). 021 is a trivial CI flip.
022 is a design spike (the one direction item with no hardware gate).

**Findings considered and NOT planned (run 4):**

- **Access/battery RX callback not loop-dispatched** — `client._handle_access_update`
  → `_handle_power_info_update` mutates battery state on the Bleak notify thread,
  inconsistent with the 007 status-thread-safety fix; the final HA write *is*
  dispatched and the mutations are atomic ref-swaps under the GIL. Low impact, low
  confidence it manifests; not planned (revisit if battery state is ever seen to
  tear under a non-loop BLE backend).
- **`async_migrate_entry` targets `minor_version=3` while the flow declares
  `MINOR_VERSION=2`** (`__init__.py:97` vs `config_flow.py:206`) — idempotent today
  (guard at `__init__.py:53`); latent footgun for a future migration. Too thin to
  plan; noted for whoever next bumps the config-flow version.
- **Per-payload TX timing debug at `transport.py:647-662`** — already left
  deliberately by plan 018 (cheap pre-evaluated scalar args); not re-opened.

## Prior runs (history, not in this tree)

Plans 001–011 ran on `advisor/*` branches (run 1: 001–005 full-color + status
spike → v0.4.0–0.4.6; run 2: 006–011 CI, thread-safety, perf, dead-code).
Settled, do not re-audit: Verge/Go/Verge Max are CCT-only (regression-tested);
light `should_poll=True` is required not redundant; protocol/crypto packing is
parity-locked to the reference implementation.
