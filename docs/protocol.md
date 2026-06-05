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

Known sample payloads generated from public Amaran Bluetooth tooling:

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
