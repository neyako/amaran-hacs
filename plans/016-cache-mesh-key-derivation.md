# Plan 016: Cache Bluetooth Mesh key derivation (K2/K4)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 0a14f9d..HEAD -- custom_components/amaran/protocol.py tests/test_protocol.py`
> If either file changed since this plan was written, compare the "Current
> state" excerpts below against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `0a14f9d`, 2026-06-20

## Why this matters

Every encrypted mesh packet — built **and** received — recomputes the same
network keys from scratch. `derive_mesh_keys(net_key, app_key)` runs the
Bluetooth Mesh K2 and K4 functions, which together perform **eight AES-CMAC
operations** (`_k2` = 5, `_k4` = 3). It is called:

- once per transmitted payload (`build_mesh_proxy_pdu`, every command and every
  poll),
- once per proxy connect (`build_proxy_filter_pdu`), and
- **once per received packet** (`decode_mesh_proxy_access`), inside the Bleak
  notification callback that runs synchronously on the Home Assistant event
  loop.

Because the integration sets a forward-all proxy filter, the proxy relays
*every* mesh message on the network to us, so the decode path fires constantly —
and it derives the keys (`protocol.py:491`) **before** the cheap NID check that
rejects foreign packets (`protocol.py:492`). The result is a steady burn of 8
AES-CMAC ops per packet on the event loop, all producing an identical result
because `net_key`/`app_key` never change for a mesh.

`derive_mesh_keys` is already a pure function of its two byte-string arguments
and returns a frozen, immutable dataclass. Memoizing it removes the entire
derivation from the steady-state TX and RX paths after the first call per mesh.

## Current state

Files and their roles:

- `custom_components/amaran/protocol.py` — command packing and mesh crypto. The
  derivation and its three callers live here. No caching today.

Relevant excerpts (verify they still match before editing):

```python
# protocol.py:3-10  (current imports — note: no functools)
from __future__ import annotations

from dataclasses import dataclass
import re

from cryptography.hazmat.primitives.cmac import CMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
```

```python
# protocol.py:345-355  (the function to cache)
def derive_mesh_keys(net_key: bytes, app_key: bytes) -> MeshKeys:
    """Derive Bluetooth Mesh K2/K4 values used by the proxy network PDU."""

    nid, encryption_key, privacy_key = _k2(net_key)
    aid = _k4(app_key)
    return MeshKeys(
        nid=nid,
        encryption_key=encryption_key,
        privacy_key=privacy_key,
        aid=aid,
    )
```

The cost it hides (do not change these — shown for context):

```python
# protocol.py:606-618
def _k2(net_key: bytes, p: bytes = b"\x00") -> tuple[int, bytes, bytes]:
    salt = _s1(b"smk2")
    t = _aes_cmac(salt, net_key)
    t1 = _aes_cmac(t, p + b"\x01")
    t2 = _aes_cmac(t, t1 + p + b"\x02")
    t3 = _aes_cmac(t, t2 + p + b"\x03")
    return t1[-1] & 0x7F, t2, t3


def _k4(app_key: bytes) -> int:
    salt = _s1(b"smk4")
    t = _aes_cmac(salt, app_key)
    return _aes_cmac(t, b"id6\x01")[-1] & 0x3F
```

The three call sites (unchanged by this plan, listed so you can confirm the hot
paths): `protocol.py:380` (`build_mesh_proxy_pdu`), `protocol.py:435`
(`build_proxy_filter_pdu`), `protocol.py:491` (`decode_mesh_proxy_access`).

`MeshKeys` is a `@dataclass(frozen=True)` (`protocol.py:21-29`) holding `int` and
`bytes` fields — immutable, so a single cached instance is safe to share across
all callers.

Why this is safe per `AGENTS.md`: the anti-pattern is *renaming internal
protocol constants without parity testing*. This plan renames nothing and changes
no byte output — it only memoizes a pure function. The existing parity tests in
`tests/test_protocol.py` (which assert exact PDU/payload bytes via round-trips)
are the parity gate and must stay green.

Repo conventions to match:
- The codebase already uses `functools.lru_cache` for exactly this kind of
  derive-once value — see `custom_components/amaran/product_catalog.py:6` (`from
  functools import lru_cache`) and `:46` (`@lru_cache(maxsize=1)` on
  `product_catalog()`). Match that idiom.
- Imports are grouped stdlib-then-third-party and sorted (ruff/isort style).

## Commands you will need

Run from the repo root (`/Users/neyako/Documents/hacs-amaran`).

| Purpose | Command | Expected on success |
|---|---|---|
| Full test suite | `python3 -m unittest discover -s tests` | last line `OK` (no `FAILED`); currently 170 tests |
| Protocol tests | `python3 -m unittest tests.test_protocol -v` | `OK` |
| Lint (non-blocking) | `ruff check custom_components/amaran` | exit 0 — **skip if `ruff` is not installed** |

**Do not use `pytest`** — a shell proxy in this environment intercepts it and
reports "no tests collected". Use `unittest` as above.

## Scope

**In scope** (modify only these):
- `custom_components/amaran/protocol.py` (add the import + one decorator)
- `tests/test_protocol.py` (add cache tests)

**Out of scope** (do NOT touch):
- `_k2`, `_k4`, `_s1`, `_aes_cmac`, `_aes_ecb`, `derive_mesh_keys`' body, or any
  packing/decoding function — no logic or byte output changes. You are only
  adding a decorator and an import.
- The three call sites — they keep calling `derive_mesh_keys(...)` exactly as
  today; the caching is transparent to them.
- `transport.py`, `client.py`, and everything else.

## Git workflow

- Branch: `advisor/016-cache-mesh-key-derivation`
- Conventional commits, matching `git log` (e.g.
  `perf(amaran): cache mesh key derivation`).
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Add the `lru_cache` import

In `custom_components/amaran/protocol.py`, add the import in stdlib-sorted order
(between `dataclasses` and `re`):

```python
from dataclasses import dataclass
from functools import lru_cache
import re
```

**Verify**: `python3 -c "import ast; ast.parse(open('custom_components/amaran/protocol.py').read())"` → exit 0 (file still parses).

### Step 2: Memoize `derive_mesh_keys`

Decorate the function. Keep its body byte-for-byte identical:

```python
@lru_cache(maxsize=8)
def derive_mesh_keys(net_key: bytes, app_key: bytes) -> MeshKeys:
    """Derive Bluetooth Mesh K2/K4 values used by the proxy network PDU.

    Cached: the derivation is a pure function of the two keys, which never change
    for a mesh, and it runs on every PDU build and every received packet.
    """

    nid, encryption_key, privacy_key = _k2(net_key)
    aid = _k4(app_key)
    return MeshKeys(
        nid=nid,
        encryption_key=encryption_key,
        privacy_key=privacy_key,
        aid=aid,
    )
```

`maxsize=8` bounds cached key material to a handful of meshes (a deployment has
one mesh, occasionally a few); both arguments are `bytes` (hashable) and the
return value is immutable, so `lru_cache` is correct here.

**Verify**: `python3 -m unittest tests.test_protocol -v` → `OK` (all existing
parity tests still pass — proves byte output is unchanged).

### Step 3: Add cache tests

Add to `tests/test_protocol.py`. The file already imports `derive_mesh_keys`
(`tests/test_protocol.py:17`) and defines module-level `NET_KEY` / `APP_KEY`
(`tests/test_protocol.py:28-29`). Add a new test class near the other classes:

```python
class DeriveMeshKeysCacheTest(unittest.TestCase):
    """derive_mesh_keys must memoize per (net_key, app_key)."""

    def test_same_keys_return_cached_instance(self) -> None:
        first = derive_mesh_keys(NET_KEY, APP_KEY)
        second = derive_mesh_keys(NET_KEY, APP_KEY)
        # Cache hit returns the identical object, not just an equal one.
        self.assertIs(first, second)

    def test_different_keys_derive_distinct_values(self) -> None:
        a = derive_mesh_keys(NET_KEY, APP_KEY)
        b = derive_mesh_keys(APP_KEY, NET_KEY)
        self.assertIsNot(a, b)
        self.assertNotEqual(
            (a.nid, a.encryption_key, a.privacy_key, a.aid),
            (b.nid, b.encryption_key, b.privacy_key, b.aid),
        )
```

**Verify**: `python3 -m unittest tests.test_protocol -v` → `OK`, including the two
new tests.

## Test plan

- New tests: `DeriveMeshKeysCacheTest` in `tests/test_protocol.py`, covering
  (1) cache hit returns the same instance (the optimization actually happens),
  (2) distinct keys still derive distinct, correct values (the cache is keyed
  correctly, not returning stale results).
- Structural pattern: the surrounding `unittest.TestCase` classes already in
  `tests/test_protocol.py`.
- Correctness/parity is covered by the *existing* tests — they assert exact
  PDU/payload bytes through `build_mesh_proxy_pdu` / `decode_mesh_proxy_access`
  (which call the now-cached function), so a green suite proves output is
  unchanged.
- Verification: `python3 -m unittest discover -s tests` → `OK`, 172 tests
  (170 existing + 2 new).

## Done criteria

ALL must hold:

- [ ] `python3 -m unittest discover -s tests` exits 0, last line `OK`, with the
      two new tests present and passing (172 total).
- [ ] `grep -n "@lru_cache" custom_components/amaran/protocol.py` shows the
      decorator on `derive_mesh_keys` (and the import line is present).
- [ ] `derive_mesh_keys`' body is unchanged from the "Current state" excerpt
      (only the decorator + docstring note added).
- [ ] `git status --porcelain` lists only `protocol.py` and `test_protocol.py`.
- [ ] `plans/README.md` status row for 016 updated.

## STOP conditions

Stop and report (do not improvise) if:

- The "Current state" excerpts do not match the live files (drift since
  `0a14f9d`) — in particular if `derive_mesh_keys` already has a decorator or its
  signature changed.
- Any existing test in `tests/test_protocol.py` fails after adding the decorator.
  A parity-test failure means the cache is returning wrong values — that is a
  real regression, not a test to "fix"; stop and report.
- `MeshKeys` is no longer a frozen/immutable dataclass (a cached mutable object
  would be unsafe to share) — stop and report.

## Maintenance notes

- The cache holds derived key material (not the raw keys, but values computed
  from them) for the process lifetime, bounded to 8 entries. The raw
  `net_key`/`app_key` are already resident for the whole session in
  `SidusTransportSettings` and config-entry data, so this does not materially
  change the integration's in-memory secret exposure. Do not log or serialize the
  cached `MeshKeys`.
- If a future change makes `derive_mesh_keys` depend on anything beyond its two
  arguments (e.g. a per-call IV index or a rotating key), the `lru_cache` becomes
  incorrect and must be removed or re-keyed. Today the IV index is *not* an input
  to key derivation (it is used in nonces downstream), so caching on the two keys
  is sound.
- Reviewer should confirm: no byte output changed (parity tests green), the
  function body is untouched, and `maxsize` is bounded (not unbounded
  `maxsize=None`, to cap key-material retention).
