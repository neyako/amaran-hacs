# Changelog

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
