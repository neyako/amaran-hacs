# Gate Review: hacs-amaran plans 019-022

recommendation: BLOCKED

## originalIntent

Implement `/Users/neyako/Documents/hacs-amaran` plans 019, 020, 021, and 022 via the OMO ulw-loop flow, exactly as written: tests-only diagnostics redaction guard, tests-only state-store key/roundtrip guard, blocking pinned Ruff CI job, docs-only telemetry entities design spike, and updated plan index. Constraints: no `custom_components` runtime/source edits, no telemetry entity/platform wiring, no push/PR/commit.

## desiredOutcome

- Plan 019: `tests/test_diagnostics.py` guards diagnostics redaction, including top-level and nested imported light keys, and proves raw key values are absent from output.
- Plan 020: `tests/test_state_store.py` guards `_state_store_key` identity stability and persisted state roundtrip shape.
- Plan 021: `.github/workflows/ci.yml` lint job is blocking and pins `ruff==0.15.18`.
- Plan 022: `docs/telemetry-design.md` is docs-only, covers at least seven required sections, and does not wire telemetry into HA runtime.
- `plans/README.md` rows for 019-022 updated.
- OMO ledger/evidence prove criteria completion with clean scope.

## userOutcomeReview

Implementation content mostly matches the requested user-visible outcome: targeted diagnostics/state-store tests pass, full `unittest` suite exits OK, Ruff exits OK, `custom_components/amaran` has no modified source files, and telemetry work is docs-only.

Gate cannot approve because required gate artifacts/status are incomplete and scope is dirty outside the requested artifact set.

## blockers

1. OMO aggregate goal remains `in_progress` in `.omo/ulw-loop/019ee4f5-8e4f-7681-9330-761d1d4f5784/goals.json`, even though criteria C001-C003 are `pass`. The durable ulw-loop status does not show completion.
2. Scope drift: `git status --porcelain=v1 --untracked-files=all` shows untracked `.opencode/opencode.db-shm` and `.opencode/opencode.db-wal`. The requested artifact scope only allowed implementation files plus `.omo/ulw-loop` evidence, not `.opencode` runtime database files.
3. Required final-gate input artifacts are absent: no code review report, no manual QA matrix, and no notepad path/artifact were found under `.omo`, `.opencode`, `plans`, `docs`, `tests`, or `.github`.
4. Required review-report coverage is absent: no artifact explicitly documents a `remove-ai-slops`/programming perspective check or overfit/slop criteria. Direct pass found no unresolved hollow-test issue, but missing report coverage is itself a gate blocker.

## directSlopPass

- `remove-ai-slops` and `programming` skills were not available on disk; criteria were applied directly.
- `tests/test_diagnostics.py` is not deletion-only or tautological. It exercises real `diagnostics.py`, checks nested redaction, and asserts raw key values do not appear anywhere in serialized diagnostics output. The local client-module stub is awkward but not hollow for the redaction contract.
- `tests/test_state_store.py` is not circular for the key formula: expected key is independently recomputed from the documented identity string and hash. Roundtrip tests check saved shape consumed by restore logic.
- No unnecessary production extraction/parsing/normalization was added. No `custom_components` runtime/source files changed.
- `docs/telemetry-design.md` stayed docs-only and does not add entity/platform wiring.

## checkedArtifactPaths

- `.omo/ulw-loop/019ee4f5-8e4f-7681-9330-761d1d4f5784/brief.md`
- `.omo/ulw-loop/019ee4f5-8e4f-7681-9330-761d1d4f5784/goals.json`
- `.omo/ulw-loop/019ee4f5-8e4f-7681-9330-761d1d4f5784/ledger.jsonl`
- `.omo/ulw-loop/evidence/019-020-targeted-tests.txt`
- `.omo/ulw-loop/evidence/021-ruff-ci.txt`
- `.omo/ulw-loop/evidence/022-final-regression.txt`
- `.omo/ulw-loop/evidence/full-discover-pre-fix.txt`
- `.github/workflows/ci.yml`
- `plans/README.md`
- `plans/019-test-diagnostics-redaction.md`
- `plans/020-test-state-store.md`
- `plans/021-make-ruff-ci-blocking.md`
- `plans/022-telemetry-entities-spike.md`
- `docs/telemetry-design.md`
- `tests/test_diagnostics.py`
- `tests/test_state_store.py`

## verificationRun

- `rtk uvx --with cryptography python -m unittest tests.test_diagnostics -v` -> OK, 3 tests.
- `rtk uvx --with cryptography python -m unittest tests.test_state_store -v` -> OK, 7 tests.
- `rtk uvx --with cryptography python -m unittest discover -s tests` -> OK, 188 tests; suite still prints the pre-existing async task warning.
- `rtk uvx ruff==0.15.18 check .` -> All checks passed.
- `git status --porcelain=v1 --untracked-files=all` -> includes expected implementation files plus blocking `.opencode` WAL/SHM files.

## evidenceGaps

- Missing completed OMO goal status.
- Missing code review report artifact.
- Missing manual QA matrix artifact.
- Missing notepad path/artifact.
- Missing explicit slop/overfit review coverage artifact.
- Out-of-scope `.opencode` dirty files present in git status.
