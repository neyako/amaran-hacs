# Amaran Home Assistant Integration - Agent Notes

## Project Goal

Local Home Assistant integration for Amaran/Sidus Mesh lights using:

* ESPHome Bluetooth Proxy
* Bluetooth Mesh Proxy
* Mesh credentials exported from Amaran Desktop

Supported:

* Amaran Ace 25c
* Amaran Pano 60c
* Amaran 60x S
* Amaran 100x S

---

## Critical Findings

### Mesh Credentials

Source of truth:

Amaran Desktop SQLite:

```text
~/Library/Application Support/amaran Desktop/*_secure_id/amaran.db
```

Contains:

* net_key
* app_key
* node_address
* model
* light metadata

Do NOT attempt to brute-force or re-discover keys.

---

### Reference Implementation

Primary reference:

https://github.com/wesbos/amaran-BLE-control

Important command types:

* HSI: 0x81
* CCT: 0x82
* Power: 0x8C
* Brightness: 0x8F

Telink opcode:

* 0x26

Prefer parity with reference implementation over new protocol guesses.

---

### Discovery

Bluetooth discovery is intentionally disabled.

Reason:

Advertisements do not contain enough information to create usable Home Assistant
devices.

Discovery caused:

* duplicate entries
* generic "amaran" devices
* user confusion

Setup flow is import-based.

---

### Import Model

User exports JSON.

User imports ONE LIGHT at a time.

Do NOT automatically create all lights from one JSON file.

Per-light config entries are intentional.

---

### Transport Architecture

Use:

```text
1 mesh transport
-> many mesh node addresses
```

NOT:

```text
1 BLE connection per light
```

Avoid per-light BLE sessions.

Proxy/transport is internal.

Users should not see:

* proxy entities
* transport entities
* mesh internals

---

### Availability

Availability is based on mesh transport readiness.

Do not mark lights unavailable merely because they have been idle.

Do not transition to stale after a few minutes of inactivity.

---

### State Restoration

Never send commands during Home Assistant startup.

Startup should:

* restore previous HA state
* mark state assumed until confirmed

Startup must NOT:

* force 100%
* force 5600K
* turn lights on

---

### User Terminology

User-facing text:

Use:

* light
* lights

Avoid:

* fixture
* fixtures

Avoid exposing:

* transport
* proxy
* mesh

except in diagnostics.

---

### Capability Mapping

RGB capable:

* Ace 25c
* Pano 60c

Expose:

* brightness
* color temperature
* HS color

Bi-color only:

* 60x S
* 100x S

Expose:

* brightness
* color temperature

Do NOT expose HS color.

---

### Product Catalog

product.json is authoritative for:

* model identification
* capabilities
* display names

Do not use it for HA branding.

---

### Battery

Battery is decoded from the Sidus `0x0A` power report and polled every 60s.

The proxy only forwards these reports once the integration sets a Bluetooth Mesh
proxy filter (forward-all) on connect; without that filter no report arrives.

Current behavior:

Battery sensor is enabled by default for battery-capable lights and shows the
real decoded percentage. It stays unavailable until a real packet is received.

Do not invent values.

Do not fake 0% or 100%.

---

### Known Working Workflow

1. User runs export script.
2. User pastes JSON.
3. User selects light.
4. Integration creates one light entry.
5. Persistent mesh transport starts.
6. Light becomes controllable.

---

### Before Large Refactors

Run manual tests:

* power
* brightness
* CCT
* HSI (RGB models)
* restart HA
* transport reconnect
* ESPHome proxy restart

Do not merge major transport changes without physical-light validation.

---

## Anti-Patterns

Do NOT:

* re-enable Bluetooth discovery
* create mesh group config entries
* create one BLE session per light
* send startup commands
* expose transport entities by default
* invent battery values
* rename internal protocol constants without parity testing

When unsure, preserve the currently working transport path.
