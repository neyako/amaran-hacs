# Plan 017: Batch mesh sequence persistence with a high-water mark

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 0a14f9d..HEAD -- custom_components/amaran/client.py tests/test_client.py tests/test_transport.py`
> If any of those changed since this plan was written, compare the "Current
> state" excerpts below against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW-MED (touches mesh sequence durability — read "Why this matters"
  and the durability argument in Step 2 carefully)
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `0a14f9d`, 2026-06-20

## Why this matters

The shared mesh sequence number is written to disk **on every single send** —
every user command *and* every background poll. The flow is:

`transport._save_sequence()` → `SidusSequenceManager.async_save()` →
`Store.async_save()` (an immediate JSON file write, not the debounced
`async_delay_save`).

Even with no user activity, each light polls state every 30s and battery every
60s (`DEFAULT_STATE_POLL_INTERVAL_SECONDS`, `DEFAULT_BATTERY_POLL_INTERVAL_SECONDS`
in `const.py:52-53`), and every poll reserves a sequence and saves. That is
roughly **3 disk writes/minute per light** at idle, multiplied by the number of
lights sharing a mesh, plus one write per command. On the SD-card / eMMC storage
typical of Home Assistant OS hosts (Raspberry Pi and friends) this is needless
flash wear and event-loop I/O churn for a value that only needs to survive a
restart.

The fix is the standard sequence-allocator pattern: persist a **high-water mark
that is ahead of current use**, and only write again when usage catches up to it.
On restart we resume from the persisted high-water (skipping a few never-sent
numbers, which is harmless — Bluetooth Mesh tolerates sequence gaps; it only
forbids *reuse*). This cuts persistence from one write per send to one write per
batch of sends, while strictly preserving the no-reuse guarantee.

Crucially, the change lives entirely inside `SidusSequenceManager`. The transport
still calls its `_save_sequence` callback every send (so the transport's own
tests are unaffected); only the *disk write inside `async_save`* is throttled.

## Current state

File and role:

- `custom_components/amaran/client.py` — `SidusSequenceManager` owns the
  persisted sequence for one mesh key/source/IV tuple. This is the only class you
  change.

The module constants block (add the new batch size here):

```python
# client.py:83-91
_STORE_VERSION = 1
_SEQUENCE_MANAGERS = f"{DOMAIN}_sequence_managers"
_MESH_NETWORKS = f"{DOMAIN}_mesh_networks"
_POWER_SETTLE_DELAY = 0.05
_MESH_MONITOR_INTERVAL = 5.0
_AVAILABLE_TRANSPORT_STATES = {
    TRANSPORT_STATE_CONNECTED,
    TRANSPORT_STATE_PROXY_READY,
}
```

The class as it exists today:

```python
# client.py:94-144
class SidusSequenceManager:
    """Shared sequence state for one mesh key/source/IV tuple."""

    def __init__(self, hass: HomeAssistant, storage_key: str) -> None:
        self._store: Store[dict[str, int]] = Store(
            hass, _STORE_VERSION, f"{DOMAIN}_{storage_key}"
        )
        self.lock = asyncio.Lock()
        self.sequence = DEFAULT_SEQUENCE
        self._loaded = False

    async def async_setup(
        self,
        *,
        initial_sequence: int,
        node_address: int,
        source_address: int,
        iv_index: int,
    ) -> None:
        """Load persisted sequence once and merge it with entry data."""

        if self._loaded:
            self.sequence = max(self.sequence, initial_sequence)
            return

        self.sequence = initial_sequence
        data = await self._store.async_load()
        if data and CONF_SEQUENCE in data:
            self.sequence = max(self.sequence, int(data[CONF_SEQUENCE]))
        self._loaded = True
        _LOGGER.debug(
            "Loaded Sidus sequence seq=%s node=0x%04x src=0x%04x iv_index=%s",
            self.sequence,
            node_address,
            source_address,
            iv_index,
        )

    async def async_save(
        self, *, node_address: int, source_address: int, iv_index: int
    ) -> None:
        """Persist the next sequence reserved for this mesh source."""

        await self._store.async_save(
            {
                CONF_SEQUENCE: self.sequence,
                CONF_NODE_ADDRESS: node_address,
                CONF_SOURCE_ADDRESS: source_address,
                CONF_IV_INDEX: iv_index,
            }
        )
```

How sequences are reserved and saved (context — **do not change** these; shown so
you understand the invariant):

```python
# transport.py:225-248  (SidusBaseTransport._reserve_sequences)
#   bumps self._sequence_manager.sequence by `count`, returns the reserved range.
# Callers reserve, then `await self._save_sequence()`, then write to BLE:
#   transport.py:737-741 (transient), 935-939 (persistent), 466-467 (proxy filter)
```

The save callback chain (context):

```python
# client.py:218        save_sequence=self._async_save_sequence,
# client.py:494-499
    async def _async_save_sequence(self) -> None:
        await self._sequence_manager.async_save(
            node_address=self._node_address,
            source_address=self._source_address,
            iv_index=self._iv_index,
        )
```

**The durability invariant** (must be preserved): before any send, the value on
disk must be `>=` every sequence number that will be transmitted, so a crash +
restart resumes strictly above all sent numbers and never reuses one. Today
`async_save` persists `self.sequence` (the next free number) after each
reservation and before the BLE write, so disk `>=` next-free `>` any sent number.

## Commands you will need

Run from the repo root (`/Users/neyako/Documents/hacs-amaran`).

| Purpose | Command | Expected on success |
|---|---|---|
| Full test suite | `python3 -m unittest discover -s tests` | last line `OK`; currently 170 tests |
| Client tests | `python3 -m unittest tests.test_client -v` | `OK` |
| Transport tests | `python3 -m unittest tests.test_transport -v` | `OK` (must stay green — see Step 1) |
| Lint (non-blocking) | `ruff check custom_components/amaran` | exit 0 — **skip if `ruff` is not installed** |

**Do not use `pytest`** — a shell proxy in this environment intercepts it and
reports "no tests collected". Use `unittest` as above.

## Scope

**In scope** (modify only these):
- `custom_components/amaran/client.py` — add one module constant and modify
  `SidusSequenceManager.__init__`, `async_setup`, and `async_save` only.
- `tests/test_client.py` — add batching tests.

**Out of scope** (do NOT touch):
- `transport.py` — the transport keeps calling `_save_sequence()` on every send;
  do not move or remove those calls. The throttling is entirely inside
  `SidusSequenceManager.async_save`.
- `tests/test_transport.py` — its `save_count == 2` assertions
  (`tests/test_transport.py:276, 319`) count callback invocations via the test's
  own `FakePersistentTransport._save_sequence`, **not** disk writes. They must
  stay at 2 and stay unchanged. If your change makes them fail, your throttling
  leaked into the wrong layer — STOP.
- The `Store` class, the storage key, and the load/merge `max(...)` logic in
  `async_setup` (you add to it, you don't change the existing merge).
- Any other class or file.

## Git workflow

- Branch: `advisor/017-batch-sequence-persistence`
- Conventional commits, matching `git log` (e.g.
  `perf(amaran): batch mesh sequence persistence`).
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Add the batch-size constant

In the constants block at `client.py:83-91`, add:

```python
# How many sequence numbers to reserve on disk per persistence write. We persist
# a high-water mark this far ahead of current use, then skip disk writes until
# use catches up. On restart we resume from the persisted high-water (a small
# forward gap of never-sent numbers — harmless; mesh forbids reuse, not gaps).
_SEQUENCE_PERSIST_BATCH = 64
```

**Verify**: `python3 -m unittest tests.test_transport -v` → `OK` (sanity: you have
not broken anything yet; transport tests must remain green throughout this plan).

### Step 2: Track and advance a persisted high-water mark

Modify `SidusSequenceManager` so it records what is currently on disk and only
writes when the in-memory `sequence` would exceed it.

2a. In `__init__`, add a high-water field initialized to `-1` (meaning "nothing
persisted yet"):

```python
    def __init__(self, hass: HomeAssistant, storage_key: str) -> None:
        self._store: Store[dict[str, int]] = Store(
            hass, _STORE_VERSION, f"{DOMAIN}_{storage_key}"
        )
        self.lock = asyncio.Lock()
        self.sequence = DEFAULT_SEQUENCE
        self._loaded = False
        self._persisted_high_water = -1
```

2b. In `async_setup`, after the load/merge sets `self.sequence`, record that the
loaded value is what is on disk. Set it in the not-yet-loaded branch (right after
`self._loaded = True`):

```python
        self.sequence = initial_sequence
        data = await self._store.async_load()
        if data and CONF_SEQUENCE in data:
            self.sequence = max(self.sequence, int(data[CONF_SEQUENCE]))
        self._loaded = True
        self._persisted_high_water = self.sequence
        _LOGGER.debug(
            "Loaded Sidus sequence seq=%s node=0x%04x src=0x%04x iv_index=%s",
            self.sequence,
            node_address,
            source_address,
            iv_index,
        )
```

Leave the `if self._loaded:` early-return branch as-is — it must NOT touch
`_persisted_high_water` (the high-water reflects disk state, set once on first
setup).

2c. Replace `async_save` with the high-water version:

```python
    async def async_save(
        self, *, node_address: int, source_address: int, iv_index: int
    ) -> None:
        """Persist a sequence high-water mark ahead of current use.

        We only write to disk when the in-memory sequence reaches the value last
        persisted, then jump the persisted mark ``_SEQUENCE_PERSIST_BATCH`` past
        current use. The persisted value is therefore always >= every sequence
        that has been sent, so a crash + restart resumes strictly above all sent
        numbers and never reuses one. Between writes this is a no-op, which is
        what removes the per-command / per-poll disk churn.
        """

        if self.sequence <= self._persisted_high_water:
            return

        high_water = self.sequence + _SEQUENCE_PERSIST_BATCH
        await self._store.async_save(
            {
                CONF_SEQUENCE: high_water,
                CONF_NODE_ADDRESS: node_address,
                CONF_SOURCE_ADDRESS: source_address,
                CONF_IV_INDEX: iv_index,
            }
        )
        self._persisted_high_water = high_water
```

**Why the durability invariant still holds.** `async_save` is called after
`_reserve_sequences` has bumped `self.sequence` to the next free number and
before the BLE write. Two cases:

- `self.sequence > _persisted_high_water`: we write `self.sequence + BATCH`
  (strictly greater than any number about to be sent) and update the mark. Disk
  is ahead. ✓
- `self.sequence <= _persisted_high_water`: we skip, relying on the previously
  persisted mark, which is `>= self.sequence > ` every number about to be sent. ✓

On a fresh install (no persisted data), `async_setup` sets
`_persisted_high_water = initial_sequence`. The first reservation makes
`self.sequence > initial_sequence`, so the **first** command/poll always writes —
no weaker durability than today on the first send.

**Verify**: `python3 -m unittest discover -s tests` → `OK`. In particular
`tests.test_transport` stays green with `save_count == 2` unchanged (those count
callback calls, not disk writes).

### Step 3: Add batching tests

Add to `tests/test_client.py`. The file installs Home Assistant stubs including a
fake `Store` that records the last saved dict in `self.data` and returns it on
load (`tests/test_client.py:40-52`, re-bound at `:97`). `SidusSequenceManager` is
defined in the client module; import it.

Add a counting Store and a test class. Put the import with the other client
imports (`tests/test_client.py:65-70` imports from `custom_components.amaran.client`)
— add `SidusSequenceManager` and the constant:

```python
from custom_components.amaran.client import (
    AmaranSidusClient,
    SidusMeshNetwork,
    SidusSequenceManager,
    get_mesh_network,
    mesh_network_key,
)
from custom_components.amaran.client import _SEQUENCE_PERSIST_BATCH
```

Then add the test class (model its async structure on the existing
`unittest.IsolatedAsyncioTestCase` classes already in this file):

```python
class _CountingStore:
    """Store stub that counts writes and keeps the last persisted dict."""

    def __init__(self) -> None:
        self.data: dict[str, Any] | None = None
        self.save_count = 0

    async def async_load(self) -> dict[str, Any] | None:
        return self.data

    async def async_save(self, data: dict[str, Any]) -> None:
        self.save_count += 1
        self.data = data


def _make_sequence_manager(store: _CountingStore) -> SidusSequenceManager:
    manager = SidusSequenceManager(object(), "test")
    manager._store = store
    return manager


class SequencePersistenceBatchingTest(unittest.IsolatedAsyncioTestCase):
    async def _reserve_and_save(self, manager: SidusSequenceManager) -> None:
        # Mirror what the transport does per send: bump sequence, then save.
        manager.sequence += 1
        await manager.async_save(node_address=2, source_address=0x000F, iv_index=0)

    async def test_persists_high_water_ahead_of_use(self) -> None:
        store = _CountingStore()
        manager = _make_sequence_manager(store)
        await manager.async_setup(
            initial_sequence=100000, node_address=2, source_address=0x000F, iv_index=0
        )

        await self._reserve_and_save(manager)  # sequence -> 100001

        self.assertEqual(store.save_count, 1)
        self.assertEqual(store.data["sequence"], 100001 + _SEQUENCE_PERSIST_BATCH)

    async def test_skips_disk_writes_within_a_batch(self) -> None:
        store = _CountingStore()
        manager = _make_sequence_manager(store)
        await manager.async_setup(
            initial_sequence=100000, node_address=2, source_address=0x000F, iv_index=0
        )

        for _ in range(_SEQUENCE_PERSIST_BATCH):
            await self._reserve_and_save(manager)

        # First save jumped the mark a full batch ahead; the rest of the batch
        # are no-ops. Exactly one disk write for a whole batch of sends.
        self.assertEqual(store.save_count, 1)

        # One more send crosses the high-water and writes again.
        await self._reserve_and_save(manager)
        self.assertEqual(store.save_count, 2)

    async def test_restart_resumes_at_or_above_persisted_high_water(self) -> None:
        store = _CountingStore()
        first = _make_sequence_manager(store)
        await first.async_setup(
            initial_sequence=100000, node_address=2, source_address=0x000F, iv_index=0
        )
        await self._reserve_and_save(first)  # persists 100001 + BATCH
        persisted = store.data["sequence"]

        # Simulate a restart: a new manager loads the same store.
        second = _make_sequence_manager(store)
        await second.async_setup(
            initial_sequence=100000, node_address=2, source_address=0x000F, iv_index=0
        )

        # Resume at the persisted high-water — never below a sent number.
        self.assertEqual(second.sequence, persisted)
        self.assertGreater(second.sequence, 100001)
```

`Any` is already imported in `tests/test_client.py` (it uses `dict[str, Any]` in
the existing Store stub). If a name is missing, check the existing imports first.

**Verify**: `python3 -m unittest tests.test_client -v` → `OK`, including the three
new tests.

## Test plan

- New tests: `SequencePersistenceBatchingTest` in `tests/test_client.py`:
  - high-water is persisted ahead of current use (the optimization writes a
    forward mark, not the bare next sequence);
  - a full batch of sends produces exactly one disk write (the churn is gone);
  - after a simulated restart, the manager resumes at the persisted high-water
    and strictly above any sent number (the no-reuse guarantee holds).
- Existing coverage that must stay green and unchanged:
  `tests/test_transport.py` `test_persistent_reuses_one_connection_and_cached_characteristic`
  and `test_persistent_serializes_concurrent_writes` (`save_count == 2`) — they
  assert callback invocations, which this plan does not change.
- Verification: `python3 -m unittest discover -s tests` → `OK`, 173 tests
  (170 existing + 3 new).

## Done criteria

ALL must hold:

- [ ] `python3 -m unittest discover -s tests` exits 0, last line `OK` (173 total),
      with the three new tests passing.
- [ ] `python3 -m unittest tests.test_transport -v` → `OK` with the two
      `save_count == 2` assertions unchanged in the source.
- [ ] `grep -n "_SEQUENCE_PERSIST_BATCH" custom_components/amaran/client.py` shows
      the constant defined and used in `async_save`.
- [ ] `grep -n "_persisted_high_water" custom_components/amaran/client.py` shows
      it set in `__init__` and `async_setup` and read in `async_save`.
- [ ] `git status --porcelain` lists only `client.py` and `test_client.py`.
- [ ] `plans/README.md` status row for 017 updated.

## STOP conditions

Stop and report (do not improvise) if:

- The "Current state" excerpts do not match the live `client.py` (drift since
  `0a14f9d`).
- Any `tests/test_transport.py` test fails, or you feel the need to edit it to
  pass — that means throttling leaked out of `SidusSequenceManager`.
- You discover another reader/writer of the sequence store beyond
  `SidusSequenceManager` (`grep -rn "CONF_SEQUENCE" custom_components/amaran`)
  that would be confused by a high-water value instead of the exact next
  sequence. (As of `0a14f9d` only this class reads/writes it.)
- A test fails twice after a reasonable fix attempt.

## Maintenance notes

- The persisted value is now a **high-water mark (ahead of use)**, not the exact
  next sequence. Anyone reading `<config>/.storage/amaran_sequence_*` directly,
  or any future migration of that store, must treat it as "resume at or above
  this", which is exactly what `async_setup`'s `max(...)` already does.
- Trade-off: each restart "wastes" up to `_SEQUENCE_PERSIST_BATCH` sequence
  numbers. The mesh sequence space is 24-bit (~16.7M) and
  `_reserve_sequences` raises `HomeAssistantError` when exhausted
  (`transport.py:231-236`). At 64 per restart this is astronomically far from
  exhaustion; do not shrink the space-saving by lowering the batch without reason,
  and if you ever *raise* the batch dramatically, reconsider exhaustion headroom.
- This does not change crash safety relative to today's first-send behavior: the
  first send after a fresh setup still persists before its BLE write.
- **Physical validation before merge** (AGENTS mandate touches the mesh path
  indirectly): after this lands, on a real light run several commands, restart
  Home Assistant, and confirm commands still take effect (a reused/too-low
  sequence would make the light silently ignore messages). Also confirm a
  power-cycle of HA mid-session does not break control.
- Reviewer should scrutinize the durability argument in Step 2: the persisted
  value must always be `>=` every transmitted sequence. The ordering
  (reserve → save → write, all under `sequence_manager.lock`) is what guarantees
  it; if a future refactor moves the save after the write, this batching becomes
  unsafe.
