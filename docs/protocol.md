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
| HSI/RGB | `0x81` |

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
| Report delivery to this HA proxy client | Live reference says replies target provisioner `0x0001`; current integration source is normally `0x000f`, has no explicit proxy-filter setup, and tests synthesize replies to `0x000f` | Unproven | Do not claim state sync yet |

The delivery caveat is material: the reference implementation found that
fixtures send replies to provisioner unicast `0x0001`, not to the requester.
Its ESP32 integration needed a passive network-layer snoop to receive them;
see the
[`Two-way sync` notes](https://github.com/wesbos/amaran-BLE-control/blob/a18ca3ccacc9e8c6264eb24fc2698af4b99b834b/esp32-firmware/README.md#L142-L177).
No `*_btatt.tsv` or other raw status capture named by the spike plan exists in
the local `artifacts/` tree, so the Home Assistant Bluetooth Mesh Proxy
delivery path cannot be proven from this checkout.

Recommendation: make the next status-sync task a transport-focused capture
spike. First prove whether Mesh Proxy Data Out forwards destination `0x0001`;
if it does not, research a standards-compliant proxy filter subscription for
`0x0001`. Do not change source addresses or add a polling loop until delivery
is demonstrated. No production status code is added by this spike.

## Effects & extended commands

### Candidates

| Candidate | Opcode / layout | Source | Confidence | Decision |
| --- | --- | --- | --- | --- |
| RGB plus warm/cool white | Command type `0x04`; setter byte 9 is `0x84`. Bits `12..21` intensity, `22..31` cool white, `32..41` warm white, `42..51` blue, `52..61` green, `62..71` red; each channel is 10-bit | `artifacts/jadx/sources/com/sidus/link/libmesh/protocol/RGBWProtocol.java:22-79` and app dispatch in `DataPacker.java:55-59` | High for byte layout; low for supported simultaneous-white behavior | Defer |
| First-generation system effects | Command type `0x07`; byte 8 is effect type. Example: Candle effect type `0x04`, then CCT bits `40..49`, frequency bits `50..53`, intensity bits `54..63` | `CandleProtocol.java:15-63`; effect dispatch table in `SystemEffectPacker.java:96-205` | High for individual packet layouts | Defer |
| Second-generation system effects | Command type `0x22` (`34`); byte 8 is effect type. Example: Lightning II effect type `0x01`, with state, intensity, frequency, speed, mode, and mode-dependent CCT/G/M or HSI fields | `LightningProtocol2.java:20-97`; dispatch in `SystemEffectPacker.java:207-294` | High for individual packet layouts | Defer |
| Effect off | Command type `0x07`, effect type `0x0f` | `EffectOffProtocol.java:9-41` | High for bytes; model-family behavior unverified | Defer |

The app has multiple effect protocol generations (`0x07`, `0x21`, `0x22`) and
per-model support flags. The bundled app config marks Ace 25c (`400U5`) and
Pano 60c (`400W5`) as `rgb_support=1`, but it does not establish that their
warm/cool-white fields may safely be mixed with RGB. It also enables a
model-specific subset of `systemfx_*` values. The integration's current
`product.json` does not carry those effect-generation or effect-list fields,
so exposing one generic list would violate the per-model evidence boundary.

The desktop WebSocket API independently exposes `set_rgb`,
`get_system_effect_list`, and `set_system_effect`, with the effect list queried
per node rather than assumed globally; see
[`amaran-cli` API reference](https://github.com/theontho/amaran-cli/blob/4aab857a772f4131cb40ca834c00fdaae6b84810/docs/API_REFERENCE.md#L766-L914).
That confirms product concepts, not raw mesh bytes.

### Home Assistant modeling

If effects are implemented later, expose only the model's verified names via
`effect_list`, accept `ATTR_EFFECT` in `async_turn_on`, report `EFFECT_OFF` when
no effect is active, and use an effect-appropriate color mode. This follows the
[Home Assistant light entity contract](https://developers.home-assistant.io/docs/core/entity/light/).

If the five RGB/white channels are validated later, model them as
`ColorMode.RGBWW` / `rgbww_color`, not HS: HS cannot preserve independent warm
and cool white channels. Do not add RGBWW from the Java class alone; first
capture a command from a supported Ace/Pano and record channel scaling and
whether simultaneous nonzero RGB + white values are accepted.

Phase B was not entered. Status decode is already present and matches the
strong sources, while its actual blocker is unproven message delivery. Effects
and RGBWW both need model-specific data or physical-light captures that this
spike explicitly does not send.

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
