# Changelog

## v0.5.0

- Add a native Effect preset dropdown to each supported color light's device
  page, using the shared HSI/RGB effect encoder and model-specific preset list.
- Add an External power indicator for battery-capable lights. Correct supply
  detection to use reported external voltage; active charging is not reported.
- Refresh all 98 products from Desktop 1.1.03 (129), using explicit per-model
  HSI, CCT, RGB, tint, and effect metadata. Enable basic HSI for catalog-supported
  color lights, including Ray 60c/120c/360c/660c, for physical validation.
- Expose model-specific CCT limits, including 1800–20000 K CCT+ where supported.
- Add native RGB with separate brightness, readback, and command-free restore.
- Add all 33 built-in system-effect presets with per-model eligibility. New
  encoders need physical validation; generation-III presets are experimental.
- Preserve old product-ID aliases when Desktop changes IDs.
- Preserve product IDs/codes in exports and exclude camera/audio/accessory rows.
- Close Desktop database connections after exporting or inspecting lights.
- Fix negative green/magenta rounding and safely ignore unauthenticated packets.
- Cancel per-light polling/subscriptions on unload without closing another
  light's shared connection.
- Restore cached states as assumed and discard unsupported cached color modes.
- Keep cached colors unconfirmed when a light reports an unsupported color mode.
- Skip redundant effect-stop packets while a light is off, fixing repeated
  `effect: off` plus color wake requests on T4c.
- Validate generic T4c HSI visually, plus brightness, 2500–7500 K CCT, signed
  tint, and all 15 first-generation effect selections through device reports.
- Validate all 12 shared Ace 25c/T4c effects with identical packets and matching
  device reports; confirm Ace 2300–10000 K CCT, signed tint, and effect dimming.
- Preserve requested RGB colors when Ace replies contain only reduced 0/1
  channel values. These reports remain assumed instead of falsely confirming
  black and erasing the color during dimming.

- Rewrite the README with simpler setup instructions, a device-page screenshot,
  and tested-model notes including Verge Max.

## v0.4.7 - 2026-06-30

### Reliability

- Recovers from stale ("zombie") BLE mesh proxy links. Writes are sent without a
  response, so a proxy whose link silently died still looked connected: every
  command succeeded locally while nothing reached the light, and the monitor
  never reconnected. A `disconnected_callback` now wakes the reconnect loop on
  real drops, and a notification-silence watchdog forces a fresh proxy connection
  when the light stops answering (no status notification for >90s after a write)
  even though `is_connected` is still True. Adds a `watchdog_reconnect_count`
  diagnostic.
- Dispatches BLE status notifications onto the event loop so a status callback
  arriving on a worker thread can no longer race or break Home Assistant state
  updates.

### Features

- Imports multiple lights in a single pass instead of one config entry at a time.
- Exposes a green/magenta tint control as a number entity for capable lights.

### Performance

- Caches mesh key derivation, batches sequence-number persistence, and guards
  hot-path logging to cut per-command overhead.
- Skips writing unchanged state to storage.

## v0.4.6 - 2026-06-19

- Chooses the strongest reachable Amaran BLE proxy in automatic mode instead of
  the first imported light, avoiding weak/stuck proxy connections that can leave
  writes optimistic and status readback stale.

## v0.4.5 - 2026-06-19

- Resolves exported light models and capabilities from the product catalog by
  product ID, code, or name, so Verge Max exports as a CCT light instead of
  `Unknown`.
- Treats legacy `model: "Unknown"` imports as missing model data so the light
  name can recover the correct catalog profile.
- Preserves color temperature when imported capabilities contain both
  brightness and color temperature.

## v0.4.0 - 2026-06-19

### Full-color light support

- Classifies MT Pro, Infinimat, and Infinibar as full-color (color temp + color)
  instead of color-temp-only, so these RGBWW fixtures expose color control. Verge,
  Go, and Verge Max are confirmed CCT-only and stay that way.
- Skips motorized accessories (Motorized Yoke, F14 Fresnel) on import — they are
  mounts, not lights.
- Migrates existing light entries on restart to re-derive their color
  capabilities, fixing lights added before this release (for example a Verge Max
  stuck on brightness-only) without deleting and re-adding them.
- Consolidates the name-classification heuristics and removes a dead lookup table
  (behavior-preserving).

### State sync

- Sets a Bluetooth Mesh proxy filter (forward-all reject list) on every
  connection so the light's status and battery reports actually reach Home
  Assistant. Without it the proxy dropped every reply addressed to us, which is
  why knob changes never synced and battery stayed unknown.
- Polls each light's state every 30s and battery every 60s with harmless status
  requests, so a physical knob change syncs back to Home Assistant and the
  battery percentage stays current. Passive status notifications still apply
  instantly when the light sends them.
- Enables the battery sensor by default for battery-capable lights now that real
  battery percentages are decoded.

### Other

- Documents Sidus status-notification decode and extended-command (effects /
  RGBWW) research in `docs/protocol.md`.
- Adds Windows support to the `export_amaran` helper script.

## v0.3.0 - 2026-06-05

- Fixes light availability so each light depends on its own BLE advertisement
  freshness plus the shared mesh transport, instead of treating a ready proxy as
  proof that every light is online.
- Keeps idle lights available, refreshes stale checks from Home Assistant's BLE
  cache, and marks only the affected light unavailable after command failures.
- Adds an advanced option to disable per-light presence checking and fall back to
  transport-only availability.
- Adds the debug-only `amaran.request_power_status` service for Sidus `0x0A`
  power-status probes and decrypted Mesh Proxy Data Out logging.
- Adds battery-status decoding plumbing and diagnostic battery entities for
  battery-capable models, while keeping sensors unavailable until a real decoded
  battery packet is received.
- Backfills battery capability on older imported Ace/PT-style entries so the
  diagnostic battery entity can appear disabled by default.

## v0.2.0 - 2026-06-05

- Initial HACS-ready release.
- Adds the `amaran` Home Assistant custom integration with JSON import setup.
- Supports per-light config entries for known Amaran lights.
- Keeps Bluetooth discovery disabled intentionally.
- Redacts mesh keys from diagnostics and helper-script listing output.
