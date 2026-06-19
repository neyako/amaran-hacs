# Changelog

## Unreleased

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
