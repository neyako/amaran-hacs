# Amaran Home Assistant Integration - Agent Notes

## Project Goal

Local Home Assistant integration for Amaran/Sidus Mesh lights using:

* ESPHome Bluetooth Proxy
* Bluetooth Mesh Proxy
* Mesh credentials exported from Amaran Desktop

Supported:

* Amaran Ace 25c (CCT, tint, and 12 effects confirmed; RGB reports may lack usable channel values)
* Amaran Pano 60c
* Amaran T4c (generic HSI visually confirmed; brightness, saturation, and CCT readback confirmed)
* Amaran 60x S
* Amaran 100x S
* Amaran Ray 120c (brightness, CCT, and green/magenta confirmed in issue #7)
* Amaran Ray 60c/120c/360c/660c (catalog-derived HSI/CCT+; hardware validation pending)

---

## Critical Findings

### Mesh Credentials

The amaran apps sync every light and the mesh keys to the Sidus account.
Primary setup signs in to that account (`cloud.py`):

* `POST https://{us|eu|cn}.sidus.link/uc/user/login` with `email`,
  `phone_number`, `password`, `area` (country code) and headers
  `platform: 2`, `request_source: 4` (without them: 10001). Code 4001 names the
  account's region in `data.OtherRegionUser[].area`; retry there.
* `GET .../amaran/pack/query` with the `Token` header returns `meshs.existing`
  (net/app keys) and `fixtures.existing` (MAC, node address, code, name).
* Region per country comes from the Android app's `country_region_data.json`.
* Never store the password or token; only the resulting light data.

Desktop fallback:

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

Advertisements alone can't create usable lights: they carry no model or keys.
The old discovery created generic "amaran" devices and duplicates.

Discovery only offers setup; it never creates an entry by itself
(`discovery.py`, `async_step_bluetooth`):

* Lights advertise the Mesh Proxy service (0x1828) with the network ID,
  k3(net_key). Manifest matchers: 0x1828 plus Telink (529) or 1014
  manufacturer data. Telink lights (60x S, Ace 25c, Verge Max) put
  `00 + MAC + 02 + node address` in manufacturer data; T4c uses 1014 with
  `01 + MAC + 02 + node address`.
* Unknown network: one card per network (`network_<id>`) that opens the normal
  sign-in/paste menu. Other brands' Telink mesh lights can also show this card.
* Network of a configured light: one card per unadded light (unique ID = MAC).
* Node Identity advertisements (type 0x01) are ignored.

---

### Import Model

User signs in or pastes an export, then ticks the lights to add.

Each ticked light becomes its own config entry. Per-light config entries are
intentional.

Do NOT create lights the user did not select.

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

Resolve capabilities from the bundled Desktop `product_capabilities.json`,
joined to `product.json` by product code. Snapshot: Desktop 1.1.03 (129).

* Basic HSI uses `hsi_support`, independently of `rgb_support` and `adv_hsi_support`.
* Bi-color lights with `hsi_support=0` must not expose HS.
* Ray 60c/120c/360c/660c have catalog IDs/codes and basic HSI enabled for validation.
  Hardware validation of the newly enabled color modes remains pending.
* CCT bounds follow each model's standard range or CCT+ extension when supported.
* Native RGB follows `rgb_support`; keep HSI compatibility where supported.
  Ace 25c reports reduce RGB channels to 0/1. Preserve requested colors as assumed
  when those replies cannot confirm them; never decode them as confirmed black.
* Built-in effect presets follow `systemfx_*` flags and the implemented encoder
  table. New RGB/effect/HSI profiles need physical validation; see
  `docs/effects-design.md` for generation-III and multipart-readback limits.
* Tint follows `gm_support`.
* Camera, audio, and motorized accessories must not create light entities.

---

### Product Catalog

product.json is authoritative for:

* model identification
* display identity
* display names

Use `product_capabilities.json` for control capabilities. Do not use either
catalog for HA branding.

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

External power is a diagnostic `plug` binary sensor based on real external
voltage from the same report. Do not label it active charging: the report does
not distinguish charging from a full battery. The Effect preset select mirrors
the light entity and uses its existing service/encoder path.

---

### Known Working Workflow

1. User signs in with their amaran account, or runs the export script and
   pastes the JSON.
2. User selects lights.
3. Integration creates one entry per selected light.
4. Persistent mesh transport starts.
5. Lights become controllable.

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

* create entries straight from Bluetooth discovery
* create mesh group config entries
* create one BLE session per light
* send startup commands
* expose transport entities by default
* invent battery values
* rename internal protocol constants without parity testing

When unsure, preserve the currently working transport path.
