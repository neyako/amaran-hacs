# Manual QA Matrix: hacs-amaran plans 019-022

Status: passed

## Surface Evidence

| Scenario | Surface | Artifact | Verdict |
| --- | --- | --- | --- |
| Plans 019-020 targeted tests | CLI/data | `.omo/ulw-loop/evidence/019-020-targeted-tests.txt` | PASS: diagnostics 3 OK, state_store 7 OK, focused Ruff OK |
| Plan 021 Ruff CI gate | CLI/data | `.omo/ulw-loop/evidence/021-ruff-ci.txt` | PASS: `ruff@0.15.18` clean, no `continue-on-error`, no advisor TODO, one `ruff==0.15.18`, YAML OK |
| Plan 022 docs and regression | CLI/data | `.omo/ulw-loop/evidence/022-final-regression.txt` | PASS: telemetry doc has 7 sections, required claims present, protected `custom_components` status clean, full suite 188 OK |

## Adversarial Checks

| Check | Expected | Verdict |
| --- | --- | --- |
| Missing evidence | All evidence files exist and are non-empty | PASS |
| Out-of-scope runtime source edits | No dirty `custom_components/amaran` files | PASS |
| Telemetry spike scope | No entity/platform/source wiring for telemetry | PASS |
| Cleanup | All spawned subagents closed; no tmux/browser/server/port spawned | PASS |

## Notes

The full-suite artifact contains a pre-existing async task warning from `tests/test_transport.py`, but the run exits `OK` after 188 tests. The local Homebrew `python3` lacks `cryptography`; full-suite QA used `uvx --with cryptography python`, matching CI's dependency installation.
