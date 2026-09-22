# Amaran Bluetooth Mesh Protocol Notes

These notes summarize the command path used by the integration. They avoid
device-specific captures, exported keys, and user database content.

## GATT Path

Provisioned Amaran lights use Bluetooth Mesh Proxy writes. Raw writes to the
vendor characteristics observed on unprovisioned devices are not enough for
local control.

| Service | Characteristic | Properties | Notes |
| --- | --- | --- | --- |
| `00001828-0000-1000-8000-00805f9b34fb` | `00002add-0000-1000-8000-00805f9b34fb` | write without response | Mesh Proxy Data In |
| `00001828-0000-1000-8000-00805f9b34fb` | `00002ade-0000-1000-8000-00805f9b34fb` | notify | Mesh Proxy Data Out |

## App Command Shape

APK inspection shows app commands flow through an Amaran command payload wrapped
in Bluetooth Mesh access opcode `0x26`.

```text
LightingClient.sendDataToMCU(nodeId, protocol)
MeshMessageClient.sendMessage(nodeId, opcode=0x26, params=10-byte payload)
Bluetooth Mesh Application Access message
Mesh Proxy Data In (2ADD)
```

Power uses the app sleep/wake command rather than Generic OnOff:

- wake / on: `SleepProtocol(1)`
- sleep / off: `SleepProtocol(0)`

Brightness uses an intensity range of `0..1000`.

Color temperature uses kelvin divided by `10` and a green/magenta offset on the
reference `-10..+10` scale.

## 10-Byte Payload

Byte `0` is the checksum: `sum(bytes[1..9]) & 0xff`.

Reference command types:

| Command | Type |
| --- | ---: |
| on/off | `0x8c` |
| brightness | `0x8f` |
| color temperature | `0x82` |
| HSI | `0x81` |
| Native RGB | `0x84` |

Known sample payloads were cross-checked against public Amaran Bluetooth tooling,
including [wesbos/amaran-BLE-control](https://github.com/wesbos/amaran-BLE-control)
and [theontho/amaran-cli](https://github.com/theontho/amaran-cli):

| Command | Payload |
| --- | --- |
| Brightness 10% | `a8 00 00 00 00 00 00 00 19 8f` |
| Brightness 22% | `c6 00 00 00 00 00 00 00 37 8f` |
| Brightness 50% | `0c 00 00 00 00 00 00 00 7d 8f` |
| CCT 3200K, 22% | `0e 00 00 00 00 40 01 14 37 82` |
| CCT 5600K, 30% | `31 00 00 00 00 40 01 23 4b 82` |
| HSI 45 deg, 60%, 80% | `fd 00 00 00 00 00 af 05 c8 81` |
| Power on | `8d 00 00 00 00 00 00 00 01 8c` |
| Power off | `8c 00 00 00 00 00 00 00 00 8c` |

The Bluetooth Mesh access payload is:

```text
26 <10-byte Amaran payload>
```

## Status notification decode

### Command and report layout

The official app parser and the live-reply decoder in
[`wesbos/amaran-BLE-control`](https://github.com/wesbos/amaran-BLE-control/blob/a18ca3ccacc9e8c6264eb24fc2698af4b99b834b/src/telink.ts#L121-L158)
agree on the 10-byte status layout. Bit numbers below treat the payload as an
80-bit little-endian value, so bit 8 is byte 1 bit 0.

HSI (`command_type = 0x01`):

| Bits | Field |
| --- | --- |
| `0..7` | checksum |
| `8` | power / sleep mode, `1` = on |
| `9..27` | reserved |
| `28` | optional HSI CCT range flag |
| `29` | optional HSI G/M format flag |
| `30` | optional HSI G/M high bit |
| `31..37` | optional HSI G/M value |
| `38..45` | optional HSI CCT |
| `46..52` | saturation `0..100` |
| `53..61` | hue `0..360` |
| `62..71` | intensity `0..1000` |
| `72..78` | command type `0x01` |
| `79` | operation type: `1` setter, `0` report |

CCT (`command_type = 0x02`):

| Bits | Field |
| --- | --- |
| `0..7` | checksum |
| `8` | power / sleep mode, `1` = on |
| `9..41` | reserved |
| `42` | CCT range flag; add 1000 to the 10-bit CCT value when set |
| `43` | G/M format flag |
| `44` | G/M high bit |
| `45..51` | G/M value |
| `52..61` | CCT in kelvin/10 |
| `62..71` | intensity `0..1000` |
| `72..78` | command type `0x02` |
| `79` | operation type: `1` setter, `0` report |

The integration's normal HSI setter leaves the optional HSI CCT/G/M fields at
zero and packs the active values as follows:

| Byte | HSI setter field |
| ---: | --- |
| `0` | checksum: `sum(bytes[1..9]) & 0xff` |
| `1..4` | zero; power is sent separately with command `0x8c` |
| `5` | saturation bits `0..1` in bits `6..7` |
| `6` | saturation bits `2..6` in bits `0..4`; hue bits `0..2` in bits `5..7` |
| `7` | hue bits `3..8` in bits `0..5`; intensity bits `0..1` in bits `6..7` |
| `8` | intensity bits `2..9` |
| `9` | `0x81` for a setter; a report carries low command type `0x01` with operation bit clear |

The CCT setter packs:

| Byte | CCT setter field |
| ---: | --- |
| `0` | checksum |
| `1..4` | zero; power is sent separately with command `0x8c` |
| `5` | CCT range flag in bit 2, G/M format in bit 3, G/M high in bit 4, G/M bits `0..2` in bits `5..7` |
| `6` | G/M bits `3..6` in bits `0..3`; CCT bits `0..3` in bits `4..7` |
| `7` | CCT bits `4..9` in bits `0..5`; intensity bits `0..1` in bits `6..7` |
| `8` | intensity bits `2..9` |
| `9` | `0x82` for a setter; a report carries low command type `0x02` with operation bit clear |

Sources: app byte packing and parsing in
`artifacts/jadx/sources/com/sidus/link/libmesh/protocol/HSIProtocol.java:64-124`
and `CCTProtocol.java:55-124`; independent live-reply implementation in
[`src/telink.ts`](https://github.com/wesbos/amaran-BLE-control/blob/a18ca3ccacc9e8c6264eb24fc2698af4b99b834b/src/telink.ts#L121-L158).

### Request and receive path

The status request is `0e 00 00 00 00 00 00 00 00 0e`, wrapped in access
opcode `0x26`. The fixture replies with its current mode: low command type
`0x01` for HSI or `0x02` for CCT. Power is byte 1 bit 0. Brightness and color
reuse the corresponding setter bitfields. Command type `0x0a` is a separate
power/battery diagnostic page, not light state. Sources: the
[`statusRequest`](https://github.com/wesbos/amaran-BLE-control/blob/a18ca3ccacc9e8c6264eb24fc2698af4b99b834b/src/telink.ts#L24-L33)
and
[`decodeStatus`](https://github.com/wesbos/amaran-BLE-control/blob/a18ca3ccacc9e8c6264eb24fc2698af4b99b834b/src/telink.ts#L121-L158)
implementations, cross-checked against the app dispatch in
`artifacts/jadx/sources/com/sidus/link/coremesh/data/DataPacker.java:28-101`.

Current integration flow:

```text
Mesh Proxy Data Out notification
-> decode_mesh_proxy_access()
-> decode_sidus_status_payload()
-> transport status_callback
-> per-node client callback keyed by source_address
-> light._handle_status_update()
```

`light._handle_status_update()` requires `power`, `brightness`, and
`color_mode`; it accepts `color_temp_kelvin` or `hs_color`, preserves the
inactive color values, marks the state confirmed (`assumed_state = false`),
persists it, and writes the HA entity state.

### Evidence and decision

| Candidate | Evidence | Confidence | Decision |
| --- | --- | --- | --- |
| Status request `0x0e` | App `LightModeProtocol`; public implementation tested against real lights | High | Already implemented byte-for-byte |
| HSI/CCT report decode | App `parseData()` plus independently live-verified decoder | High | Existing integration decoder matches |
| Report delivery to this HA proxy client | The transport installs an empty reject-list proxy filter on every connection, forwarding reports regardless of destination | Implemented | Validate delivery on each new model |

The reference implementation found replies addressed to provisioner unicast
`0x0001`, rather than the requester. The integration now sets a forward-all
Bluetooth Mesh proxy filter on connect, polls state every 30 seconds, and polls
battery every 60 seconds. Decoded reports are dispatched by source node address.
No source-address change is needed. These are status requests, not startup
power or color commands.

External supply presence comes from `0x0a` bytes 7–8 (external voltage), matching
the SDK's power UI. A nonzero value means external power, not necessarily active
charging. The previous bit-23 supply interpretation was incorrect. Battery-capable
lights expose this as a diagnostic `plug` binary sensor; it stays unavailable
until a real power report arrives. Ace 25c reports 15000 mV while plugged in.

Cached state is always assumed after restart until a fresh report arrives.
Per-light poll timers and battery subscriptions are cancelled when the entry
unloads; other lights retain their shared connection.

## Effects and extended commands

Native RGB uses setter `0x84`, with intensity at bit 12 and RGB at bits
62/52/42. The app's RGB constructor uses `ceil(channel * 1000 / 255)`, power
bit 8, and zero white channels. See [native RGB and RGBWW](rgbww-design.md).

The catalog records basic HSI, native RGB, advanced HSI, CCT+, tint, and system
effect capabilities separately. Basic HSI uses the existing common `0x81`
packet. CCT+ uses `0x82` with the existing range bit, up to 20000 K, only on
profiles advertising that range. Mixed RGBWW and advanced HSI are separate
capabilities and are not inferred from a basic color flag.

All 33 system-effect variants have preset encoders and per-model filtering.
Their setters use command bytes `0x87` and `0xa2`; some newer effects require
two packets. See [built-in effects](effects-design.md) for the full mapping,
default provenance, deliberate test presets, and readback limitations.

Native RGB, CCT+, and other newly enabled profiles still need physical validation.
The capability implementation was completed before the user disclosed the test
model. The user subsequently selected the T4c and authorized importing its
Desktop export; no model-specific encoder changes were made for validation.

### T4c live validation, 2026-09-22

Home Assistant 2026.9.2 imported one T4c through the normal JSON config flow.
The light advertised HSI, 2500–7500 K CCT, tint, and 15 base system effects.
It did not advertise native RGB or CCT+, so those protocols cannot be validated
with this light.

Device reports confirmed HSI red/green/blue, 50% saturation, brightness changes
preserving the selected HSI color, and both CCT endpoints. The user also visually
confirmed the red/green/blue sequence. Confirmation required fresh reports with
`assumed_state=false`; a successful write or optimistic HA state did not count.
All 15 first-generation system-effect presets also confirmed their selection
and intensity through device reports. Effect dimming preserved its selection,
and explicit effect-off returned to CCT. Raw CCT reports confirmed green/magenta
values of -5 and +5 after the signed-rounding fix; tint was then reset to neutral.
Generation II/III remain untested on hardware.
Repeated `effect: off` plus HSI wake requests initially failed while the light
was off. Skipping the redundant effect-stop packet fixed the repeated request
and waking into HSI from a cached Fire effect. The normal HSI encoder was not
changed. Core restart preserved off state; entry reload reconnected and confirmed
the previous HSI state. Neither path sent startup control commands.
The light started off and was returned to off after each test batch.

### Ace 25c comparison, 2026-09-22

Ace and T4c accepted byte-identical packets for all 12 shared first-generation
effects at 5% intensity. Both returned the requested effect and intensity, and
the user saw effects on both. Ace also confirmed effect dimming, effect-off to
CCT, 2300 K and 10000 K endpoints, and raw green/magenta reports of -5 and +5.
Its Desktop profile has no extended CCT range; the 1800–20000 K path remains
unvalidated on hardware.

Native RGB red and magenta were visually confirmed on Ace. Its RGB reports reduce channel
values to 0/1 and cannot distinguish mixed colors reliably. They now update
power/intensity while preserving the requested RGB color as assumed; see
[RGB readback limits](rgbww-design.md). No model-specific RGB/effect encoder
or guessed replacement opcode was introduced.

## Mesh Values

Home Assistant needs values from the user's own Amaran Desktop export:

- 16-byte network key
- 16-byte app key
- destination node address
- IV index
- source address
- monotonically increasing 24-bit sequence number

HCI logs alone do not reveal the decrypted access payload. Use
`scripts/export_amaran.py` to export the local Desktop database into JSON, and
keep that JSON private.

## Proof Of Concept

Print raw Amaran payloads:

```bash
python3 scripts/amaran_ace25c_poc.py --power on --brightness 22 --cct 3200
```

Print encrypted proxy PDUs with fake example keys:

```bash
python3 scripts/amaran_ace25c_poc.py \
  --address AA:BB:CC:DD:EE:01 \
  --net-key 00112233445566778899aabbccddeeff \
  --app-key ffeeddccbbaa99887766554433221100 \
  --node-address 0x0002 \
  --source-address 0x000f \
  --sequence 100000 \
  --iv-index 0 \
  --power on \
  --brightness 22
```

Use `--send` only with your own light address and your own exported keys.
