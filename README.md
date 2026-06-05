# amaran

Home Assistant custom integration for local control of supported Amaran lights
over Bluetooth Mesh.

## What It Does

- Adds Amaran lights to Home Assistant as light entities.
- Controls power, brightness, color temperature, and HS color where supported.
- Imports the Bluetooth Mesh keys and light metadata exported from amaran
  Desktop.
- Creates one independent Home Assistant config entry per light.
- Uses optimistic state until the integration can decode more status data.

## Supported Lights

Currently mapped models:

- amaran 100x / 100x S: brightness and color temperature
- amaran 60x S: brightness and color temperature
- amaran Ace 25c: brightness, color temperature, and HS color
- amaran Pano 60c: brightness, color temperature, and HS color

Unknown models default to brightness and color temperature when imported.

## Requirements

- Home Assistant with Bluetooth available.
- A provisioned Amaran light already paired in the official app.
- amaran Desktop on macOS, or a copied amaran Desktop database.
- Export JSON from this repository's `scripts/export_amaran.py` helper.

An ESPHome Bluetooth Proxy close to the lights is recommended for reliable
Bluetooth coverage, especially when Home Assistant runs far from the lights.

## HACS Installation

1. In HACS, add this repository as a custom repository.
2. Select category `Integration`.
3. Install `amaran`.
4. Restart Home Assistant.
5. Go to Settings -> Devices & services -> Add integration -> amaran.

HACS installs the integration under:

```text
custom_components/amaran
```

## Export JSON Setup Flow

The integration setup flow expects pasted export JSON. The export contains
the mesh keys Home Assistant needs plus each light name, model, address, and
capabilities.

On macOS, from a clone of this repository:

```bash
python3 scripts/export_amaran.py | pbcopy
```

Then in Home Assistant:

1. Add the `amaran` integration.
2. Choose import setup.
3. Paste the copied JSON.
4. Select exactly one light.
5. Repeat Add integration with the same JSON for each additional light.

The JSON shape also accepts a `lights` list, or the integration's native
`fixtures` key, for compatibility with existing Amaran Bluetooth tooling.

## Security Warning

Exported JSON contains Bluetooth Mesh keys. Anyone with those keys and local
Bluetooth access may be able to control your lights.

Do not share exported JSON publicly. Do not attach it to issues, logs,
screenshots, or support threads.

Diagnostics redact `net_key`, `app_key`, and pasted JSON fields.

## Known Limitations

- Battery is unavailable until decoded from real status data.
- State sync is best-effort and optimistic.
- Changes made in the official app may not instantly sync yet.
- Bluetooth discovery is disabled intentionally. Add lights from export JSON.

## Advanced Notes

Manual setup is available for advanced users who already know the required
mesh values. Prefer the JSON import flow unless you are debugging.

For debug logging:

```yaml
logger:
  logs:
    custom_components.amaran: debug
```

The disabled diagnostic sensor and config entry diagnostics expose connection
details for troubleshooting.
