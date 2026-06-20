# Plan 021: Make the ruff CI job blocking on a pinned version

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 2193a35..HEAD -- .github/workflows/ci.yml pyproject.toml`
> If either changed since this plan was written, compare the "Current state"
> excerpts below against the live files before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S (XS change; the care is in pinning so the gate is stable)
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `2193a35`, 2026-06-20

## Why this matters

The CI lint job is non-blocking — `continue-on-error: true` with a standing TODO
to "make ruff blocking once existing findings are cleared" (`ci.yml:30-32`,
introduced by advisor-006). That precondition is now **met**: `ruff check .`
passes cleanly on the current tree (verified with `ruff` 0.15.18 — the version in
the repo's `.ruff_cache/`). So the only thing the TODO is waiting on is already
done; the job should be flipped to blocking so a future lint regression fails the
PR instead of scrolling past in a green check.

One real risk to handle while doing it: the lint step currently does
`pip install --upgrade pip ruff` (`ci.yml:39-40`) — an **unpinned** ruff. If the
job becomes blocking on an unpinned tool, a future ruff release that adds a new
default lint rule could fail CI on code that was clean the day before, with no
change from the contributor. The fix is to **pin ruff** to the known-good version
at the same time as making it blocking. That converts the job from "ignored" to
"deterministic gate".

## Current state

`.github/workflows/ci.yml:29-42` (the lint job):

```yaml
  lint:
    name: Ruff
    # TODO(advisor-006): make ruff blocking once existing findings are cleared
    continue-on-error: true
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Install ruff
        run: python -m pip install --upgrade pip ruff
      - name: Ruff check
        run: ruff check .
```

`pyproject.toml` configures ruff but selects no extra rule families (so only
ruff's default rule set — `E4/E7/E9/F` — is enforced; `line-length = 88` does
**not** enable `E501`, which is why the tree passes clean):

```toml
# pyproject.toml:1-9
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint.per-file-ignores]
# Tests and scripts install Home Assistant stubs into sys.modules before
# importing the integration, so module-level imports intentionally follow code.
"scripts/*" = ["E402"]
"tests/*" = ["E402"]
```

The known-good ruff version is **0.15.18** (present at
`.ruff_cache/0.15.18/` in the tree; `ruff check .` passes at it).

## Commands you will need

Run from the repo root (`/Users/neyako/Documents/hacs-amaran`).

| Purpose | Command | Expected on success |
|---|---|---|
| Verify lint passes at the pin | `uvx ruff@0.15.18 check .` | last line `All checks passed!`, exit 0 |
| Fallback if `uvx` unavailable, `ruff` installed | `ruff check .` | `All checks passed!`, exit 0 |
| Full test suite (unaffected, sanity) | `python3 -m unittest discover -s tests` | last line `OK`, **178** tests |

If neither `uvx` nor a local `ruff` is available, you cannot verify locally — say
so in your report and rely on the CI run; do **not** skip the pin.

## Scope

**In scope** (modify only):
- `.github/workflows/ci.yml` — the `lint` job only.

**Out of scope** (do NOT touch):
- `pyproject.toml` — do **not** add new ruff rule selections (e.g. `select = [...]`,
  import sorting `I`, `E501`). Enabling new rules is a separate, opinionated change
  that would surface new findings and break the now-blocking gate; it is
  deliberately deferred (see Maintenance notes). This plan **only** makes the
  existing, already-passing check blocking and deterministic.
- The `test` and `validate` jobs in `ci.yml`.
- Any source file.

## Git workflow

- Branch: `advisor/021-make-ruff-ci-blocking`
- Conventional commits, matching `git log` (e.g.
  `ci(amaran): make ruff blocking on a pinned version`).
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Confirm the tree is still lint-clean at the pin

**Verify**: `uvx ruff@0.15.18 check .` → `All checks passed!` (exit 0).

If this reports findings, **STOP** — the TODO's precondition is no longer met and
this plan's premise is invalid. Report the findings instead of making the job
blocking (a separate cleanup plan would be needed first).

### Step 2: Pin ruff and remove the non-blocking escape hatch

Edit the `lint` job in `.github/workflows/ci.yml`:

- Delete the `# TODO(advisor-006): ...` comment line.
- Delete the `continue-on-error: true` line.
- Change the install step to pin ruff to `0.15.18`.

Target shape:

```yaml
  lint:
    name: Ruff
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Install ruff
        run: python -m pip install --upgrade pip "ruff==0.15.18"
      - name: Ruff check
        run: ruff check .
```

**Verify**: `grep -n "continue-on-error" .github/workflows/ci.yml` → no match in
the `lint` job (there is none elsewhere either, so expect **no output**).
`grep -n "ruff==0.15.18" .github/workflows/ci.yml` → one match.

### Step 3: Sanity-check the workflow file is still valid YAML

**Verify**:
`python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"`
→ prints `yaml ok`. (If `pyyaml` is not installed, skip this check and instead
re-read the file to confirm indentation matches the target shape exactly.)

## Test plan

- No unit tests change (this is CI config). The guard is the CI run itself: after
  this lands, a PR that introduces a ruff violation will fail the now-blocking
  `Ruff` check.
- Local verification is `uvx ruff@0.15.18 check .` → clean, proving the gate will
  pass on the current tree.

## Done criteria

ALL must hold:

- [ ] `uvx ruff@0.15.18 check .` (or `ruff check .`) → `All checks passed!`,
      exit 0. (If no ruff is available locally, note that in the report.)
- [ ] `.github/workflows/ci.yml` lint job has **no** `continue-on-error` and **no**
      `TODO(advisor-006)` comment.
- [ ] The lint install step pins `ruff==0.15.18`.
- [ ] `git status --porcelain` lists only `.github/workflows/ci.yml`.
- [ ] `plans/README.md` status row for 021 updated.

## STOP conditions

Stop and report (do not improvise) if:

- `ruff check .` reports any finding at version 0.15.18 — the premise (tree is
  clean) is false; do not make the job blocking.
- The `ci.yml` lint job no longer matches the "Current state" excerpt (drift).
- You feel tempted to also enable new ruff rules to "improve" the lint — that is
  explicitly out of scope; stop and propose it separately.

## Maintenance notes

- **Deferred follow-up (intentional):** enabling a richer ruleset (import sorting
  `I`, `E501` line length, `UP` pyupgrade, `B` bugbear) would catch more, but each
  surfaces new findings that must be cleared first and is an opinion call for the
  maintainer. Do it as its own plan: add `[tool.ruff.lint] select = [...]`, clear
  the findings, then verify the (now-blocking) job still passes.
- When intentionally bumping the pinned ruff, run `ruff check .` at the new version
  locally first; a new default rule may surface findings to clear before the bump
  can land (that is the pin doing its job).
- The `test` job runs on py3.11–3.13; ruff's `target-version` is `py311`
  (`pyproject.toml:3`). Keep them consistent if the support floor ever moves.
