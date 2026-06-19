# Plan 013: Import multiple lights in one pass (multi-select at setup)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 49d7685..HEAD -- custom_components/amaran/config_flow.py custom_components/amaran/fixtures.py custom_components/amaran/strings.json custom_components/amaran/translations/en.json`
> If any of those changed since this plan was written, compare the "Current
> state" excerpts below against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (config-flow change; per-entry creation path)
- **Depends on**: none
- **Category**: direction (DX / onboarding)
- **Planned at**: commit `49d7685`, 2026-06-20

## Why this matters

Setup today imports **one** light per pass: the user pastes the export JSON,
picks a single light, and must repeat the whole "Add integration → paste JSON →
select" loop for every additional light (`README.md:92`,
`config_flow.py:362-395`). For a multi-light rig this is the single biggest
onboarding friction. The machinery to create many per-light entries already
exists and is used by the migration code (`__init__.py:103-108` spawns extra
entries via `flow.async_init(..., context={"source": SOURCE_IMPORT}, data=...)`).
This plan turns the selection step into a **multi-select** that creates one
independent config entry per chosen light in a single pass.

This preserves the project's hard rule: **one config entry per light** (see
`AGENTS.md` "Per-light config entries are intentional"). It does **not** create a
mesh-group entry and does **not** re-enable discovery.

## Current state

- `custom_components/amaran/config_flow.py` — the selection step is single-select
  and creates exactly one entry:
  ```python
  # config_flow.py:362-395
      async def async_step_select_fixture(
          self, user_input: dict[str, Any] | None = None
      ) -> config_entries.ConfigFlowResult:
          """Select the first fixture from an imported mesh catalog."""
          data = self._pending_import
          if data is None:
              return await self.async_step_import()
          catalog = list(data[CONF_FIXTURE_CATALOG])
          choices = fixture_selection_choices(catalog)
          if user_input is not None:
              fixture = fixture_for_unique_id(
                  catalog, str(user_input[CONF_SELECTED_FIXTURE])
              )
              if fixture is None:
                  return self.async_show_form(... errors={CONF_SELECTED_FIXTURE: "invalid_input"})
              entry_data = fixture_entry_data(data, fixture)
              return await self._async_create_fixture_entry(entry_data)
          return self.async_show_form(
              step_id="select_fixture",
              data_schema=self._fixture_selection_schema(choices),
              errors={},
              description_placeholders={
                  "light_count": str(len(catalog)),
                  "source": str(data.get(CONF_IMPORT_PATH) or "pasted JSON"),
                  "detected_lights": _detected_light_summary(catalog),
              },
          )

  # config_flow.py:397-404
      async def _async_create_fixture_entry(
          self, data: dict[str, Any]
      ) -> config_entries.ConfigFlowResult:
          await self.async_set_unique_id(fixture_unique_id(data))
          self._abort_if_unique_id_configured()
          return self.async_create_entry(title=str(data[CONF_NAME]), data=data)

  # config_flow.py:406-416  (single-select schema)
      @callback
      def _fixture_selection_schema(self, choices: dict[str, str]) -> vol.Schema:
          default_fixture = next(iter(choices))
          return vol.Schema(
              {
                  vol.Required(
                      CONF_SELECTED_FIXTURE,
                      default=default_fixture,
                  ): vol.In(choices)
              }
          )
  ```
  `config_flow.py` already imports `from homeassistant import config_entries`
  (top) and lazily uses `config_entries.SOURCE_IMPORT` elsewhere. `CONF_SELECTED_FIXTURE_IDS`
  is already imported is **not** — check the import block; `CONF_SELECTED_FIXTURE`
  is imported (`config_flow.py:31`). You will add `CONF_SELECTED_FIXTURE_IDS`.

- `custom_components/amaran/const.py` — both keys already exist:
  ```python
  # const.py:34-35
  CONF_SELECTED_FIXTURE = "selected_fixture"
  CONF_SELECTED_FIXTURE_IDS = "selected_fixture_ids"
  ```

- `custom_components/amaran/fixtures.py` — selection helpers exist and are pure:
  ```python
  # fixtures.py:223-241
  def fixture_entry_data(import_data, fixture) -> dict[str, Any]:
      """Build one direct fixture config entry from imported mesh data."""
      data = {**import_data, **fixture}
      for key in (CONF_FIXTURE_CATALOG, CONF_FIXTURES, CONF_IMPORT_JSON,
                  CONF_IMPORT_METHOD, CONF_IMPORT_PATH, CONF_SELECTED_FIXTURE,
                  CONF_SELECTED_FIXTURE_IDS, CONF_SETUP_METHOD):
          data.pop(key, None)
      return data

  # fixtures.py:243-253
  def fixture_selection_choices(fixtures) -> dict[str, str]:
      """Return config-flow choices keyed by stable fixture ID."""
      # returns {fixture_unique_id(f): "Name (Model) - caps", ...}

  # fixtures.py:280-288
  def fixture_for_unique_id(fixtures, fixture_id) -> dict[str, Any] | None:
  ```

- `custom_components/amaran/__init__.py` — **the spawn pattern to mirror** (this
  is exactly how extra per-light entries are created):
  ```python
  # __init__.py:100-108
      if grouped:
          from homeassistant import config_entries
          for fixture in migration_fixtures[1:]:
              await hass.config_entries.flow.async_init(
                  DOMAIN,
                  context={"source": config_entries.SOURCE_IMPORT},
                  data=_fixture_entry_data_with_capabilities(data, fixture),
              )
  ```
  The `SOURCE_IMPORT` flow lands in `async_step_import`, which creates a direct
  entry when the data already contains `CONF_ADDRESS`:
  ```python
  # config_flow.py:289-301
      async def async_step_import(self, user_input=None):
          if user_input is not None:
              if CONF_ADDRESS in user_input:
                  return await self._async_create_fixture_entry(dict(user_input))
              ...
  ```
  `fixture_entry_data(...)` output always contains `CONF_ADDRESS`
  (`fixtures.py:474`), so a spawned import flow creates one entry directly.

- `custom_components/amaran/strings.json` and `translations/en.json` — the
  `select_fixture` step text (both files, currently identical for this step):
  ```json
  "select_fixture": {
    "title": "Select light",
    "description": "Select one light from {light_count} lights found in {source}. This creates one independent integration entry. Repeat Add integration to add another light.\n\nDetected lights:\n{detected_lights}",
    "data": { "selected_fixture": "Light" }
  }
  ```

**Hard wording constraint** — `tests/test_ux_strings.py:14-28` asserts the words
`fixture`, `proxy`, and `transport` never appear in any **string value** of
`translations/en.json` (JSON keys are exempt — only values are scanned). New
user-facing text must say "light"/"lights".

## Commands you will need

Run from the repo root.

| Purpose | Command | Expected |
|---|---|---|
| Full suite | `python3 -m unittest discover -s tests` | last line `OK` |
| Selection tests | `python3 -m unittest tests.test_config_selection -v` | `OK` |
| Strings test | `python3 -m unittest tests.test_ux_strings -v` | `OK` |
| Lint (non-blocking) | `ruff check custom_components/amaran` | exit 0 — skip if `ruff` absent |

**Do not use `pytest`** (intercepted in this environment). Use `unittest`.

## Scope

**In scope**:
- `custom_components/amaran/fixtures.py` (add one pure helper)
- `custom_components/amaran/config_flow.py` (rewrite the selection step + schema)
- `custom_components/amaran/strings.json` (the `select_fixture` block only)
- `custom_components/amaran/translations/en.json` (the `select_fixture` block only)
- `tests/test_config_selection.py` (add helper tests)

**Out of scope**:
- `__init__.py` migration code — it already works; do not refactor it to share
  the new helper.
- Any other config-flow step (manual, import_json, import_path, options).
- `fixture_entry_data` / `fixture_selection_choices` / `fixture_for_unique_id` —
  reuse, do not modify.
- The per-light proxy/source-address handling — shared import settings already
  ride along in `import_data` and are copied into every entry by
  `fixture_entry_data`; do not add per-light override UI here.

## Git workflow

- Branch: `advisor/013-multi-light-import`
- Conventional commit, e.g. `feat(amaran): import multiple lights in one pass`.
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add a pure fan-out helper in `fixtures.py`

Append a helper that converts a selection into a stable, de-duplicated,
already-configured-aware list of entry-data dicts (one per chosen light, in
catalog order):

```python
def fixture_entries_for_selection(
    import_data: dict[str, Any],
    catalog: list[dict[str, Any]],
    selected_ids: list[str],
    *,
    skip_ids: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Return one entry-data dict per selected light, in catalog order.

    Skips IDs in ``skip_ids`` (already-configured) and de-duplicates.
    """

    selected = set(selected_ids)
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fixture in catalog:
        fixture_id = fixture_unique_id(fixture)
        if fixture_id not in selected or fixture_id in skip_ids or fixture_id in seen:
            continue
        seen.add(fixture_id)
        entries.append(fixture_entry_data(import_data, fixture))
    return entries
```

**Verify**: `python3 -m unittest discover -s tests` → `OK` (nothing calls it
yet).

### Step 2: Make the selection schema multi-select

Replace `_fixture_selection_schema` (`config_flow.py:406-416`) with a multi-select
over the same `{id: label}` choices, defaulting to all:

```python
    @callback
    def _fixture_selection_schema(self, choices: dict[str, str]) -> vol.Schema:
        from homeassistant.helpers import config_validation as cv

        return vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_FIXTURE_IDS,
                    default=list(choices),
                ): cv.multi_select(choices)
            }
        )
```

The lazy `import ... as cv` inside the method matches the existing lazy-import
idiom (`config_flow.py:101 from homeassistant import config_entries`) and keeps
import-time test stubs simple.

Add `CONF_SELECTED_FIXTURE_IDS` to the `from .const import (...)` block at the top
of `config_flow.py`. You may leave `CONF_SELECTED_FIXTURE` imported (still used by
`fixture_entry_data`'s pop list — but that's in `fixtures.py`; in `config_flow.py`
it is no longer referenced after this step, so remove the `CONF_SELECTED_FIXTURE`
import if and only if `grep -n CONF_SELECTED_FIXTURE config_flow.py` shows no
remaining use, to avoid an unused-import lint error).

### Step 3: Rewrite `async_step_select_fixture` to fan out

```python
    async def async_step_select_fixture(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select one or more lights from an imported mesh catalog."""

        data = self._pending_import
        if data is None:
            return await self.async_step_import()

        catalog = list(data[CONF_FIXTURE_CATALOG])
        configured = frozenset(self._async_current_ids())
        choices = {
            fixture_id: label
            for fixture_id, label in fixture_selection_choices(catalog).items()
            if fixture_id not in configured
        }
        if not choices:
            return self.async_abort(reason="already_configured")

        placeholders = {
            "light_count": str(len(choices)),
            "source": str(data.get(CONF_IMPORT_PATH) or "pasted JSON"),
            "detected_lights": _detected_light_summary(catalog),
        }

        if user_input is not None:
            selected_ids = list(user_input.get(CONF_SELECTED_FIXTURE_IDS) or [])
            entries = fixture_entries_for_selection(
                data, catalog, selected_ids, skip_ids=configured
            )
            if not entries:
                return self.async_show_form(
                    step_id="select_fixture",
                    data_schema=self._fixture_selection_schema(choices),
                    errors={CONF_SELECTED_FIXTURE_IDS: "invalid_input"},
                    description_placeholders=placeholders,
                )
            for extra in entries[1:]:
                await self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": config_entries.SOURCE_IMPORT},
                    data=extra,
                )
            return await self._async_create_fixture_entry(entries[0])

        return self.async_show_form(
            step_id="select_fixture",
            data_schema=self._fixture_selection_schema(choices),
            errors={},
            description_placeholders=placeholders,
        )
```

Notes:
- `self._async_current_ids()` is a built-in `ConfigFlow` method returning the set
  of already-configured unique IDs; filtering the choices by it prevents
  re-adding a configured light and avoids the whole flow aborting on a duplicate
  primary.
- `fixture_unique_id` (used inside the helper and `_async_create_fixture_entry`)
  is the same ID space as `_async_current_ids()` populates (entries set their
  unique_id to `fixture_unique_id(data)` — `config_flow.py:402`).
- Imports needed in `config_flow.py`: add `fixture_entries_for_selection` to the
  `from .fixtures import (...)` block.

**Verify**: `python3 -m unittest discover -s tests` → `OK`.

### Step 4: Update `select_fixture` strings (both files)

In **both** `custom_components/amaran/strings.json` and
`custom_components/amaran/translations/en.json`, replace the `select_fixture`
block with:

```json
      "select_fixture": {
        "title": "Select lights",
        "description": "Select one or more lights from {light_count} found in {source}. Each selected light becomes its own independent integration entry.\n\nDetected lights:\n{detected_lights}",
        "data": {
          "selected_fixture_ids": "Lights"
        }
      },
```

Touch only this block; leave every other step, the `import` descriptions, and the
abort/error text exactly as they are. Confirm no new value contains the words
`fixture`, `proxy`, or `transport` (the JSON key `selected_fixture_ids` is a key,
not a value, so it is allowed).

**Verify**: `python3 -m unittest tests.test_ux_strings -v` → `OK`.

## Test plan

Add tests to `tests/test_config_selection.py` (it already imports the fixtures
helpers and builds `_fixture(...)` dicts; **add `fixture_entries_for_selection` to
its `from custom_components.amaran.fixtures import (...)` block**). Model them on
the existing `test_import_selection_builds_one_direct_fixture_entry`
(`tests/test_config_selection.py:88-108`):

- `test_selection_fan_out_returns_entry_per_selected_in_catalog_order`: catalog
  `[ace, pano, sixty]`, `selected_ids=[id(pano), id(ace)]` → result has 2 entries
  named `["Ace", "Pano"]` (catalog order, not selection order), neither
  containing `CONF_FIXTURE_CATALOG`/`CONF_FIXTURES`.
- `test_selection_fan_out_skips_already_configured`: `skip_ids={fixture_unique_id(ace)}`
  with all three selected → result excludes Ace.
- `test_selection_fan_out_dedupes_repeated_ids`: duplicate IDs in `selected_ids`
  → each light appears once.
- `test_selection_fan_out_empty_selection_returns_empty`: `selected_ids=[]` → `[]`.

These cover the risk-bearing logic without instantiating the HA config-flow
runtime (consistent with how `test_config_selection.py` already avoids it).

**Verify**: `python3 -m unittest discover -s tests` → `OK`, new tests included.

## Done criteria

ALL must hold:

- [ ] `python3 -m unittest discover -s tests` exits 0, last line `OK`, new tests
      present and passing.
- [ ] `python3 -m unittest tests.test_ux_strings -v` → `OK` (no "fixture/proxy/
      transport" leaked into `en.json` values).
- [ ] `grep -n "cv.multi_select" custom_components/amaran/config_flow.py` matches.
- [ ] `grep -n "fixture_entries_for_selection" custom_components/amaran/fixtures.py
      custom_components/amaran/config_flow.py` matches in both.
- [ ] `git status --porcelain` lists only in-scope files.
- [ ] `plans/README.md` status row for 013 updated.

## STOP conditions

Stop and report (do not improvise) if:

- The "Current state" excerpts do not match the live files (drift since
  `49d7685`).
- `cv.multi_select` is unavailable in the target HA `config_validation` module.
- `self._async_current_ids()` is not present on the `ConfigFlow` base in the
  target HA version (older core) — report so an alternative dup-check can be
  chosen; do not silently drop the duplicate guard.
- A spawned `SOURCE_IMPORT` flow does not create an entry (i.e. `async_step_import`
  no longer creates a direct entry from `CONF_ADDRESS` data) — that means the
  import path changed; stop.
- A test fails twice after a reasonable fix attempt.

## Maintenance notes

- This keeps **one entry per light**. If anyone later asks for a single grouped
  entry, that contradicts `AGENTS.md` — push back, don't implement it here.
- The fan-out reuses `fixture_entry_data`, which copies shared import settings
  (source address, IV index, sequence, TTL, proxy MAC) into every entry. If
  per-light overrides for those are ever added, `fixture_entries_for_selection`
  is where the per-light values must be merged in.
- Reviewer should confirm: selecting N lights yields exactly N entries, selecting
  an already-configured light is impossible (filtered out), and the wording
  passes `test_ux_strings`.
- The `import_json`/`import_path` schemas still collect one shared
  `source_address`/`sequence`/etc. for the whole batch — that is intentional;
  every imported light in one mesh shares those.
