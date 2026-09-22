# Native RGB and RGBWW

## Current implementation

Native RGB uses the APK `RGBWProtocol` RGB-only constructor and is enabled by
Desktop's `rgb_support` flag. It keeps independent intensity and sets both
white channels to zero. HA exposes `RGB` alongside `HS` and `COLOR_TEMP` where
the corresponding capabilities are present. Brightness is implicit in these
color modes; `BRIGHTNESS` must not be advertised alongside them.

The source is the original checkout's
`artifacts/jadx/sources/com/sidus/link/libmesh/protocol/RGBWProtocol.java`.
Its constructor converts 8-bit RGB with `ceil(channel * 1000 / 255)` and its
report getters round back to 8-bit values. Desktop 1.1.03 (129)'s
`PyMeshSDK.so` uses the same `RGBWPacket::toData` layout and command 4.

| Bits | Field |
| --- | --- |
| 0..7 | checksum |
| 8 | power, 1 in the RGB constructor |
| 9..11 | reserved, zero |
| 12..21 | intensity, 0..1000 |
| 22..31 | cool white, zero for native RGB |
| 32..41 | warm white, zero for native RGB |
| 42..51 | blue, 0..1000 |
| 52..61 | green, 0..1000 |
| 62..71 | red, 0..1000 |
| 72..79 | 0x84 setter, 0x04 report |

The encoder, readback, restored state, and brightness-in-RGB behavior have unit
coverage. Reports containing nonzero independent white channels are not decoded
as native RGB, because that would lose part of the light's color state.

## Ace 25c validation, 2026-09-22

The user visually confirmed native RGB red and red+blue magenta at 10% intensity.
The `(64, 128, 255)` mixed request was described as mostly cyan; its on-device
channel values could not be checked, so exact mixed-color ratios are unverified.
Ace's legacy
RGB reports reduced the requested channels to 0/1: red returned
`ab610600000000400004`, green `7b610600000010000004`, and blue
`6f610600000400000004`. A mixed request `(64, 128, 255)` returned the same
channel values as blue, so those replies cannot reconstruct the actual color.

The decoder accepts their power/intensity but leaves RGB unknown when every raw
channel is at most 1. The entity preserves its requested color and remains
assumed, preventing the old decode-to-black behavior from erasing the color on
the next brightness change. This conservative rule also leaves genuine black
and extremely low-channel reports assumed. Full-scale replies remain decodable;
RGBWW replies with independent whites remain unsupported. No guessed scaling
or alternate opcode is used to manufacture confirmation.

Live dimming from 10% to 5% and back preserved the requested magenta channels
in both HA and the transmitted RGB packet. Fresh replies confirmed intensity
while color remained assumed. The transition from RGB to HSI also confirmed.

Accurate RGB color readback on Ace remains unverified. Packet parity alone does
not establish color accuracy or simultaneous white-channel control.

`ColorMode.RGBWW` remains unimplemented. Before exposing it, confirm simultaneous
RGB plus independent warm/cool white behavior with real hardware. Native RGB
support does not establish that capability. Existing HS automations retain HS
support; native RGB does not require removing it.
