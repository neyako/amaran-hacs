# RGB and System Effects Implementation Plan

**Status:** Implemented and deployed to Home Assistant 2026.9.2. T4c HSI is visually confirmed; CCT, tint, brightness, and all 15 base effects have fresh device readback. Additional-model validation remains pending.
**Goal:** Native HA RGB and per-model system effects without new connections or startup commands.

**Evidence:** Original checkout APK `RGBWProtocol.java` confirms RGB channels
`ceil(channel * 1000 / 255)`, intensity 0..1000, power bit 8, command 0x84,
RGB fields 62/52/42, and zero white channels for its RGB constructor. Reports
use the same fields. Desktop `rgb_support` gates native RGB independently of HSI.
Effect codecs must similarly match the SDK and each product's support flag.

**Files:** Existing protocol, commands, client, state, state_store, light,
transport, product_catalog modules and their focused unittest modules.

- [x] Add RGB packet parity/readback and state/mode/restore checks.
- [x] Add RGB encoding and native HA control, preserving independent brightness.
- [x] Persist RGB, retain HSI compatibility, and keep restart command-free.
- [x] Establish system effect mappings/defaults from SDK, then expose only
  implemented per-model effects via native HA effect selection.
- [x] Verify full unittest suite and pinned Ruff, document protocol provenance
  and pending physical checks for the undisclosed test light.

Mixed RGB plus white channels and advanced HSI remain separate protocols; native
RGB does not claim simultaneous white-channel control. The test model was withheld during implementation; the user later authorized
a T4c Desktop export for live validation.

## Verification

- `python3 -m unittest discover -s tests`: 213 tests pass.
- `uvx --from ruff==0.15.18 ruff check .`: pass.
- `git diff --check`: pass.
- [x] Import T4c through the normal Desktop JSON flow and visually confirm HSI red/green/blue/off.
- [x] Confirm power, saturation, dimming, 2500–7500 K CCT, signed tint, and all 15 base effects through device reports.
- [x] Fix and confirm repeated effect-off/HSI wake requests, including a cached Fire effect.
- [x] Confirm Core restart preserves off state and entry reload reconnects/restores HSI, both without startup control commands.
- [x] Compare all 12 shared Ace/T4c effects using identical packets, matching reports, and user visual confirmation.
- [x] Confirm Ace 2300–10000 K CCT, signed tint, and effect dimming.
- [x] Fix truncated Ace RGB replies overwriting the requested color with black; keep incomplete color state assumed.
- [x] Add device-page Effect preset selects using the shared light service;
  confirm Fire, return to steady CCT, off synchronization, and no wake when
  selecting off on both Ace 25c and T4c. Both lights were left off.
- [x] Add External power from real voltage reports; confirm Ace reports 15000 mV
  and its HA device page shows Plugged in beside the battery percentage.
- [x] Verify native dropdown options in the HA UI and no startup control commands
  after deploying all 29 integration files and restarting Core.
- [ ] Validate accurate native RGB color readback, 1800–20000 K extended CCT, and generation II/III effects; neither tested light advertises the extended CCT/effect generations.
