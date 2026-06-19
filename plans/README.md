# Plans

Reconciled 2026-06-20 against HEAD `6f26391` (`main`). Suite: `python3 -m
unittest discover -s tests` → **165 OK**.

| Plan | Status | Notes |
| --- | --- | --- |
| 012 | DONE (verified) | `012-green-magenta-cct-tint.md` — committed `6f26391`; scope clean, done criteria hold. Physical-light validation still pending before relying on it. |
| 013 | DONE (uncommitted) | `013-multi-light-import.md` — implemented in working tree (config_flow/fixtures/strings/en.json + tests), in-scope only, suite green. **Not yet committed.** |
| 014 | DONE (verified) | `014-effects-capture-spike.md` — design in `docs/effects-design.md` (7 sections); docs-only, `product.json` untouched. Build gated on real-light capture. |
| 015 | DONE (verified) | `015-rgbww-capture-spike.md` — design in `docs/rgbww-design.md` (7 sections); docs-only, no encoder/entity wiring. Build gated on mixed RGB+white real-light capture. |

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

## Prior runs (history, not in this tree)

Plans 001–011 ran on `advisor/*` branches (run 1: 001–005 full-color + status
spike → v0.4.0–0.4.6; run 2: 006–011 CI, thread-safety, perf, dead-code).
Settled, do not re-audit: Verge/Go/Verge Max are CCT-only (regression-tested);
light `should_poll=True` is required not redundant; protocol/crypto packing is
parity-locked to the reference implementation.
