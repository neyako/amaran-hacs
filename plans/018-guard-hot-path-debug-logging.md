# Plan 018: Guard hot-path debug logging against eager formatting

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 0a14f9d..HEAD -- custom_components/amaran/transport.py custom_components/amaran/client.py tests/test_transport.py tests/test_client.py`
> If any of those changed since this plan was written, compare the "Current
> state" excerpts below against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW (logging only — no control-flow or byte-output change)
- **Depends on**: none (independent of 016/017; can land in any order)
- **Category**: perf
- **Planned at**: commit `0a14f9d`, 2026-06-20

## Why this matters

Python evaluates a logging call's arguments **before** the logging framework
decides whether the level is enabled. So `_LOGGER.debug("...", payload.hex(" "))`
runs `payload.hex(" ")` every time, even when debug logging is off (the default).
On the two genuinely hot paths this is wasted work on the Home Assistant event
loop:

- **RX (`transport._handle_proxy_out_notification`)** runs for *every* packet the
  proxy forwards — and because the integration sets a forward-all filter, that is
  every mesh message on the network. It calls `raw.hex(" ")` /
  `access_payload.hex(" ")` per packet.
- **TX (`transport._write_reserved`)** runs for every transmitted payload —
  every user command *and* every background poll. It builds an extra
  `access_payload(...)` object purely to log it, plus `.hex(" ")` strings.

The per-light command methods in `client.py` do the same (`.hex(" ")` plus, in
one case, building a whole extra payload just to log it) on the user-command
path. None of this output is needed unless debug logging is explicitly enabled.

The fix is the standard guard: wrap log-only work in
`if _LOGGER.isEnabledFor(logging.DEBUG):`. Behavior is identical when debug is on;
when it is off, the formatting and throwaway allocations disappear.

## Current state

`logging` is already imported in both files (`transport.py:8`, `client.py:9`), and
each module already has `_LOGGER = logging.getLogger(__name__)`
(`transport.py:30`, `client.py:81`). The `isEnabledFor` idiom is not yet used
anywhere in the package — you are introducing it.

### RX path — `transport.py`

```python
# transport.py:503-540  (_handle_proxy_out_notification, the per-packet callback)
    def _handle_proxy_out_notification(self, _sender: Any, data: Any) -> None:
        raw = bytes(data)
        self._metrics.notification_count += 1
        self._metrics.last_notification_time = time.time()
        self._ever_received_notification = True
        if is_proxy_filter_status(raw):
            self._metrics.filter_status_count += 1
            _LOGGER.debug(
                "Sidus proxy filter status received len=%s raw=%s",
                len(raw),
                raw.hex(" "),
            )
            return
        decoded = decode_mesh_proxy_access(
            net_key=self._settings.net_key,
            app_key=self._settings.app_key,
            iv_index=self._settings.iv_index,
            proxy_pdu=raw,
        )
        if decoded is None:
            _LOGGER.debug(
                "Sidus Mesh Proxy Data Out notification len=%s type=0x%02x raw=%s",
                len(raw),
                raw[0] & 0x3F if raw else -1,
                raw.hex(" "),
            )
            return
        self._notify_access_callback(decoded)
        status = decoded.sidus_status
        if status is None:
            _LOGGER.debug(
                "Sidus decoded access src=0x%04x dst=0x%04x seq=%s access=%s",
                decoded.source_address,
                decoded.destination_address,
                decoded.sequence,
                decoded.access_payload.hex(" "),
            )
            return
```

Three debug calls here each build a hex string (`raw.hex(" ")` /
`decoded.access_payload.hex(" ")`). The `status notification` debug further down
(`transport.py:553-563`) passes only scalar status fields (no `.hex`) — **leave it
unchanged**.

### TX path — `transport.py`

```python
# transport.py:597-640  (inside _write_reserved's per-payload loop)
        for index, (current_sequence, sidus_payload) in enumerate(
            zip(sequences, sidus_payloads)
        ):
            access = access_payload(sidus_payload)
            _LOGGER.debug(
                "Sidus payload write light=%s light_mac=%s light_node=0x%04x "
                "selected_ble_mac=%s dst=0x%04x seq=%s src=0x%04x "
                "sidus=%s access=%s",
                fixture_name,
                fixture_mac,
                node_address,
                self._last_bluetooth_device["address"]
                if self._last_bluetooth_device
                else None,
                node_address,
                current_sequence,
                self._settings.source_address,
                sidus_payload.hex(" "),
                access.hex(" "),
            )
            proxy_pdu = build_mesh_proxy_pdu(
                net_key=self._settings.net_key,
                app_key=self._settings.app_key,
                src=self._settings.source_address,
                dst=node_address,
                seq=current_sequence,
                iv_index=self._settings.iv_index,
                sidus_payload=sidus_payload,
                ttl=self._settings.ttl,
            )
            _LOGGER.debug(
                "Writing Sidus proxy PDU seq=%s src=0x%04x dst=0x%04x "
                "iv_index=%s ttl=%s resolved_address=%s len=%s header=%s",
                current_sequence,
                self._settings.source_address,
                node_address,
                self._settings.iv_index,
                self._settings.ttl,
                self._last_bluetooth_device["address"]
                if self._last_bluetooth_device
                else None,
                len(proxy_pdu),
                proxy_pdu[:2].hex(),
            )
            write_start = time.perf_counter()
            ...
```

`access = access_payload(sidus_payload)` (line 600) is built **only** for the
first debug call. The `proxy_pdu = build_mesh_proxy_pdu(...)` build is the **real
work that must always run** — only its trailing debug call is log-only. The
`write_start` / write_end timing debug calls below (`transport.py:642-657`) pass
only scalars — **leave them unchanged**.

### Command builders — `client.py`

`access_payload` is imported into `client.py` (`from .protocol import
access_payload, normalize_hex_key`, `client.py:71-74`) and, within these three
methods, is used **only** inside the debug logs.

```python
# client.py:1058-1088  (async_set_brightness_cct — note `payload` is log-only)
        brightness = _clamp_brightness(brightness)
        kelvin = _clamp_kelvin(kelvin)
        gm_value = (
            self._desired_green_magenta if gm is None else _clamp_green_magenta(gm)
        )
        sidus_intensity = round(brightness / 255 * 1000)
        payload = brightness_cct_payload(
            brightness=brightness,
            kelvin=kelvin,
            gm=gm_value,
        )
        _LOGGER.debug(
            "Combined Sidus request brightness_ha=%s cct_kelvin=%s "
            "sidus_intensity=%s sidus=%s access=%s power_on=%s",
            brightness,
            kelvin,
            sidus_intensity,
            payload.hex(" "),
            access_payload(payload).hex(" "),
            power_on,
        )

        await self.async_send_siduses(
            cct_payloads(
                brightness=brightness,
                kelvin=kelvin,
                power_on=power_on,
                gm=gm_value,
            ),
            ...
```

Here both `sidus_intensity` (line 1063) and `payload` (lines 1064-1068) exist
**only** to feed the debug call — the actual send uses `cct_payloads(...)`, which
rebuilds its own payloads internally. Both can move inside the guard.

```python
# client.py:1101-1112  (async_set_brightness — `payloads` IS the real send; only the log is log-only)
        sidus_intensity = round(brightness / 255 * 1000)
        payloads = brightness_payloads(brightness=brightness, power_on=power_on)
        _LOGGER.debug(
            "Brightness Sidus request brightness_ha=%s sidus_intensity=%s "
            "sidus=%s access=%s power_on=%s",
            brightness,
            sidus_intensity,
            payloads[-1].hex(" "),
            access_payload(payloads[-1]).hex(" "),
            power_on,
        )
```

```python
# client.py:1168-1185  (async_set_hsi — `payloads` IS the real send; only the log is log-only)
        sidus_intensity = round(brightness / 255 * 1000)
        payloads = hsi_payloads(
            brightness=brightness,
            hue=hue,
            saturation=saturation,
            power_on=power_on,
        )
        _LOGGER.debug(
            "HSI Sidus request brightness_ha=%s hue=%s saturation=%s "
            "sidus_intensity=%s sidus=%s access=%s power_on=%s",
            brightness,
            hue,
            saturation,
            sidus_intensity,
            payloads[-1].hex(" "),
            access_payload(payloads[-1]).hex(" "),
            power_on,
        )
```

In the latter two, `payloads = ...` must stay where it is (it is the real send).
Only `sidus_intensity` and the `_LOGGER.debug(...)` move into the guard.

**The one rule that protects correctness:** guard only *log-only* work. Never
move a counter increment (`+= 1`), an early `return`, `self._notify_access_callback(decoded)`,
the `proxy_pdu = build_mesh_proxy_pdu(...)` build, or the real `payloads = ...` /
`cct_payloads(...)` send into a debug guard.

## Commands you will need

Run from the repo root (`/Users/neyako/Documents/hacs-amaran`).

| Purpose | Command | Expected on success |
|---|---|---|
| Full test suite | `python3 -m unittest discover -s tests` | last line `OK`; currently 170 tests |
| Transport tests | `python3 -m unittest tests.test_transport -v` | `OK` |
| Client tests | `python3 -m unittest tests.test_client -v` | `OK` |
| Lint (non-blocking) | `ruff check custom_components/amaran` | exit 0 — **skip if `ruff` is not installed** |

**Do not use `pytest`** — a shell proxy in this environment intercepts it and
reports "no tests collected". Use `unittest` as above.

## Scope

**In scope** (modify only these):
- `custom_components/amaran/transport.py` — guard the 3 RX debug calls + the 2 TX
  debug calls described above.
- `custom_components/amaran/client.py` — guard the 3 command-builder debug blocks.
- `tests/test_transport.py` — add one RX guard test.
- `tests/test_client.py` — add two command-builder guard tests.

**Out of scope** (do NOT touch):
- The `status notification` debug at `transport.py:553-563` and the timing debug
  calls at `transport.py:642-657` — they pass scalars only; leave them.
- Any non-debug log (`_LOGGER.info` / `.warning` / `.error`) anywhere.
- Any control flow: counters, returns, callbacks, and the real payload/PDU builds
  stay exactly where they are and always run.
- `protocol.py` and every other file.

## Git workflow

- Branch: `advisor/018-guard-hot-path-debug-logging`
- Conventional commits, matching `git log` (e.g.
  `perf(amaran): guard hot-path debug logging`).
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Guard the RX notification debug logs (`transport.py`)

In `_handle_proxy_out_notification`, wrap each of the three `.hex`-bearing debug
calls. Keep every counter, `decode_mesh_proxy_access(...)` call, callback, and
`return` exactly as-is.

- Filter-status branch:
  ```python
        if is_proxy_filter_status(raw):
            self._metrics.filter_status_count += 1
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(
                    "Sidus proxy filter status received len=%s raw=%s",
                    len(raw),
                    raw.hex(" "),
                )
            return
  ```
- Undecodable branch (`if decoded is None:`): wrap its `_LOGGER.debug(...)` in
  `if _LOGGER.isEnabledFor(logging.DEBUG):`, leave the `return`.
- No-status branch (`if status is None:`): wrap its `_LOGGER.debug(...)` in
  `if _LOGGER.isEnabledFor(logging.DEBUG):`, leave the `return`.

**Verify**: `python3 -m unittest tests.test_transport -v` → `OK` (behavior
unchanged).

### Step 2: Guard the TX write debug logs (`transport.py`)

In `_write_reserved`'s loop:

- Move the `access = access_payload(sidus_payload)` line **inside** a guard with
  the first debug call:
  ```python
        for index, (current_sequence, sidus_payload) in enumerate(
            zip(sequences, sidus_payloads)
        ):
            if _LOGGER.isEnabledFor(logging.DEBUG):
                access = access_payload(sidus_payload)
                _LOGGER.debug(
                    "Sidus payload write light=%s light_mac=%s light_node=0x%04x "
                    "selected_ble_mac=%s dst=0x%04x seq=%s src=0x%04x "
                    "sidus=%s access=%s",
                    fixture_name,
                    fixture_mac,
                    node_address,
                    self._last_bluetooth_device["address"]
                    if self._last_bluetooth_device
                    else None,
                    node_address,
                    current_sequence,
                    self._settings.source_address,
                    sidus_payload.hex(" "),
                    access.hex(" "),
                )
            proxy_pdu = build_mesh_proxy_pdu(
                ...  # unchanged — real work, always runs
            )
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(
                    "Writing Sidus proxy PDU seq=%s src=0x%04x dst=0x%04x "
                    "iv_index=%s ttl=%s resolved_address=%s len=%s header=%s",
                    ...  # same args as today, including proxy_pdu[:2].hex()
                )
            write_start = time.perf_counter()
            # ... rest of the loop body unchanged ...
  ```

`access` is now defined only inside the first guard; confirm it is referenced
nowhere outside that guard (it is not, today).

**Verify**: `python3 -m unittest tests.test_transport -v` → `OK`.

### Step 3: Guard the command-builder debug logs (`client.py`)

For each of the three methods, wrap the log-only work in
`if _LOGGER.isEnabledFor(logging.DEBUG):`.

- `async_set_brightness_cct`: move **both** `sidus_intensity = ...` and the
  `payload = brightness_cct_payload(...)` build and the `_LOGGER.debug(...)` into
  the guard (all three are log-only here). The `gm_value`, `brightness`,
  `kelvin`, the `await self.async_send_siduses(cct_payloads(...))`, and the
  `self._desired_*` assignments stay outside, unchanged.
- `async_set_brightness`: keep `payloads = brightness_payloads(...)` outside
  (it is the real send); move `sidus_intensity = ...` and the `_LOGGER.debug(...)`
  into the guard.
- `async_set_hsi`: keep `payloads = hsi_payloads(...)` outside; move
  `sidus_intensity = ...` and the `_LOGGER.debug(...)` into the guard.

Target shape (using `async_set_brightness` as the model):

```python
        brightness = _clamp_brightness(brightness)
        payloads = brightness_payloads(brightness=brightness, power_on=power_on)
        if _LOGGER.isEnabledFor(logging.DEBUG):
            sidus_intensity = round(brightness / 255 * 1000)
            _LOGGER.debug(
                "Brightness Sidus request brightness_ha=%s sidus_intensity=%s "
                "sidus=%s access=%s power_on=%s",
                brightness,
                sidus_intensity,
                payloads[-1].hex(" "),
                access_payload(payloads[-1]).hex(" "),
                power_on,
            )

        await self.async_send_siduses(
            payloads,
            first_payload_delay=_POWER_SETTLE_DELAY if power_on else 0.0,
        )
```

**Verify**: `python3 -m unittest tests.test_client -v` → `OK`.

### Step 4: Add guard tests

4a. `tests/test_client.py` — the file uses `import ... as client_module`
(`tests/test_client.py:64`) and a `_make_cct_client(mesh)` helper used by
`GreenMagentaClientTest` (`tests/test_client.py:447-450`); `cct_payload_ha` is
already imported (`:75`). Add `from unittest import mock` if not present, then add:

```python
class HotPathLoggingGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_brightness_cct_skips_log_only_work_when_debug_off(self) -> None:
        mesh = FakePollMesh(ready=True)
        client = _make_cct_client(mesh)
        with mock.patch.object(
            client_module._LOGGER, "isEnabledFor", return_value=False
        ), mock.patch.object(
            client_module, "access_payload", wraps=client_module.access_payload
        ) as access_spy:
            await client.async_set_brightness_cct(brightness=200, kelvin=5000)

        # Log-only access_payload() never ran when debug was disabled...
        access_spy.assert_not_called()
        # ...but the real command still went out correctly.
        self.assertEqual(
            mesh.sent[-1][0],
            [cct_payload_ha(brightness=200, kelvin=5000, gm=0)],
        )

    async def test_brightness_cct_logs_when_debug_on(self) -> None:
        mesh = FakePollMesh(ready=True)
        client = _make_cct_client(mesh)
        with mock.patch.object(
            client_module._LOGGER, "isEnabledFor", return_value=True
        ), mock.patch.object(
            client_module, "access_payload", wraps=client_module.access_payload
        ) as access_spy:
            await client.async_set_brightness_cct(brightness=200, kelvin=5000)

        # When debug is enabled the log-only path runs (proves the guard, not a deletion).
        access_spy.assert_called()
```

4b. `tests/test_transport.py` — add `from unittest import mock` if not present and
`import custom_components.amaran.transport as transport_module`. The file already
defines `FakePersistentTransport` and `FakeSequenceManager`. Add:

```python
class RxLoggingGuardTest(unittest.TestCase):
    def test_filter_status_notification_skips_hex_when_debug_off(self) -> None:
        transport = FakePersistentTransport(sequence_manager=FakeSequenceManager())
        raw = b"\x02\x03\x01\x00\x00"  # is_proxy_filter_status() is True for this
        with mock.patch.object(
            transport_module._LOGGER, "isEnabledFor", return_value=False
        ), mock.patch.object(transport_module._LOGGER, "debug") as debug:
            transport._handle_proxy_out_notification(None, raw)

        # The counter still advanced (real work), but no debug formatting ran.
        self.assertEqual(transport.metrics["filter_status_count"], 1)
        debug.assert_not_called()
```

**Verify**: `python3 -m unittest tests.test_client tests.test_transport -v` →
`OK`, including the three new tests.

## Test plan

- New tests:
  - `HotPathLoggingGuardTest` (`tests/test_client.py`): the log-only
    `access_payload(...)` is skipped when debug is off and the command still
    sends correctly; it runs when debug is on (proving the guard wraps, not
    deletes, the log).
  - `RxLoggingGuardTest` (`tests/test_transport.py`): the per-packet
    filter-status path advances its counter but emits no debug call when debug is
    off.
- Behavior-unchanged coverage: the entire existing suite must stay green — these
  changes alter no control flow, no byte output, and no log content when debug is
  enabled.
- Verification: `python3 -m unittest discover -s tests` → `OK`, 173 tests
  (170 existing + 3 new).

## Done criteria

ALL must hold:

- [ ] `python3 -m unittest discover -s tests` exits 0, last line `OK` (173 total),
      with the three new tests passing.
- [ ] `grep -c "isEnabledFor" custom_components/amaran/transport.py` ≥ 5
      (3 RX + 2 TX guards).
- [ ] `grep -c "isEnabledFor" custom_components/amaran/client.py` ≥ 3
      (the three command builders).
- [ ] In `transport.py`, `access = access_payload(sidus_payload)` appears only
      inside an `isEnabledFor` guard (`grep -n "access = access_payload"` then
      confirm the preceding line is the guard).
- [ ] No `_LOGGER.info` / `.warning` / `.error` call was wrapped (only `.debug`).
- [ ] `git status --porcelain` lists only the four in-scope files.
- [ ] `plans/README.md` status row for 018 updated.

## STOP conditions

Stop and report (do not improvise) if:

- The "Current state" excerpts do not match the live files (drift since
  `0a14f9d`).
- Any existing test fails after guarding — guarding is behavior-preserving, so a
  failure means a counter, return, callback, or real payload build was moved into
  a guard by mistake. Re-check; do not "fix" by changing the test.
- A test fails twice after a reasonable fix attempt.
- You find a debug call whose arguments have **side effects** beyond formatting
  (none are expected — they are all reads/`.hex()`); if one does, stop and report
  rather than guarding it.

## Maintenance notes

- New debug logs on these hot paths (the per-packet RX callback, the per-write TX
  loop, the per-command builders) should follow the same `isEnabledFor` guard
  whenever an argument does non-trivial work (`.hex()`, building a payload,
  joining a list). Cheap scalar args do not need a guard.
- Reviewer should confirm: when debug logging is enabled, the logged output is
  byte-for-byte the same as before (nothing was dropped — the guards wrap, they
  do not delete), and no control flow moved inside a guard.
- This plan is independent of 016 (key-derivation cache) and 017 (sequence
  batching); after 016 lands, the RX path's dominant cost is already gone and
  these guards remove the residual per-packet string formatting.
