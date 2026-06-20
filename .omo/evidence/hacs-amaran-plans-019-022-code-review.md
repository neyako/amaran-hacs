# Code Quality Review: hacs-amaran plans 019-022

Review date: 2026-06-20
Repo: `/Users/neyako/Documents/hacs-amaran`
Scope: final read-only review of plans 019-022 implementation, excluding unrelated `.opencode` and unrelated pre-existing plan content.

## Verdict

- codeQualityStatus: CLEAR
- recommendation: APPROVE
- blockers: none

## Skill-Perspective Check

- Loaded/consulted project RTK guidance and `karpathy-guidelines`.
- Searched configured skill roots for `remove-ai-slops` and `programming`; neither skill file was installed/available in this session. Applied the review criteria from the prompt directly.
- Result: no remove-ai-slops violations found. The tests are additive regression guards, not deletion-only, tautological, or requested-removal checks. No unnecessary production parsing/data extraction was added.
- Result: no programming-perspective violations found. The tests are narrowly scoped to existing contracts, no untyped production escape hatches or needless source abstractions were introduced, and the telemetry spike stayed documentation-only.

## Findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

None.

### LOW

None.

## Scope Review

- `git status --short` showed intended tracked changes in `.github/workflows/ci.yml` and `plans/README.md`, intended untracked files `docs/telemetry-design.md`, `tests/test_diagnostics.py`, `tests/test_state_store.py`, plan files, and `.omo` evidence.
- `git status --short custom_components tests docs .github/workflows/ci.yml plans/README.md` showed no dirty `custom_components` files.
- No telemetry platform/entity wiring was added. `docs/telemetry-design.md:91-92` explicitly states the spike does not change platform tuples, entity modules, client code, protocol code, or command path.
- `plans/README.md:17-20` marks plans 019-022 as `DONE (verified)`.

## Test Relevance And Maintainability

- `tests/test_diagnostics.py:194-220` exercises the diagnostics payload path and asserts top-level/nested mesh keys are redacted, raw key hex never appears in serialized diagnostics, and runtime diagnostics stay key-free even when the fake client carries raw keys in `.data`.
- `tests/test_state_store.py:72-132` pins the storage identity and saved payload shape. The sha1 expectation is intentionally a characterization of the persisted-state contract, not a tautology, because changing it would orphan existing stored light state.
- No production code was added for plans 019 or 020. The Home Assistant stubs are local to the tests and consistent with existing test style.
- `.github/workflows/ci.yml:29-40` makes Ruff blocking by removing `continue-on-error` and pins `ruff==0.15.18`, so the gate is deterministic.
- `docs/telemetry-design.md:53-69` preserves the "never invent values" rule, and `docs/telemetry-design.md:96-97` gates proposed telemetry entities to battery-capable lights.

## Verification Run

- `rtk env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_diagnostics -v` -> 3 tests OK.
- `rtk env PYTHONDONTWRITEBYTECODE=1 uvx --with cryptography python -m unittest tests.test_state_store -v` -> 7 tests OK.
- `rtk uvx ruff==0.15.18 check .` -> `All checks passed!`.
- `rtk env PYTHONDONTWRITEBYTECODE=1 uvx --with cryptography python -m unittest discover -s tests` -> 188 tests OK.
- A plain local `python3 -m unittest tests.test_state_store -v` failed because this local `python3` lacks `cryptography`; the CI-equivalent `uvx --with cryptography` run passed. CI installs `cryptography` in `.github/workflows/ci.yml:24-27`.
- The full suite still prints an unrelated async task exception from `tests/test_transport.py:254` / `custom_components/amaran/transport.py:832`, then exits `OK`. This review did not treat that as a blocker because no 019-022 diff touched that path and the requested success criterion was a green unittest discover run.

## Evidence Inspected

- `.omo/ulw-loop/evidence/019-020-targeted-tests.txt`
- `.omo/ulw-loop/evidence/021-ruff-ci.txt`
- `.omo/ulw-loop/evidence/022-final-regression.txt`
- Live file contents and live verification commands above.
