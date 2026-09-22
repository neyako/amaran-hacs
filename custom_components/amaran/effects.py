"""System-effect presets derived from the app's Effect/Protocol classes.

First/second-generation defaults come from the app; III uses test presets.
HA brightness supplies intensity. These are SDK layouts, not light captures.
The catalog flag must also be present before a light exposes a preset.
"""

from __future__ import annotations

# name: (Desktop flag, command, effect ID, default fields, intensity bit)
# Complex first-generation presets use the app's default HSI mode (1).
EFFECTS: dict[str, tuple[str, int, int, int, int]] = {
    "Club lights": ("club_lights", 0x07, 0, 5 << 50, 54),
    "Paparazzi": ("paparazzi", 0x07, 1, (10 << 33) | (560 << 40) | (5 << 50), 54),
    "Lightning": ("lightning", 0x07, 2, (5 << 27) | (2 << 31) | (10 << 33) | (560 << 40) | (5 << 50), 54),
    "TV": ("tv", 0x07, 3, 5 << 50, 54),
    "Candle": ("candle", 0x07, 4, 5 << 50, 54),
    "Fire": ("fire", 0x07, 5, 5 << 50, 54),
    "Strobe": ("strobe", 0x07, 6, (2 << 28) | (100 << 30) | (5 << 56) | (1 << 60), 46),
    "Explosion": ("explosion", 0x07, 7, (1 << 28) | (100 << 30) | (5 << 56) | (1 << 60), 46),
    "Faulty bulb": ("faulty_bulb", 0x07, 8, (5 << 24) | (2 << 28) | (100 << 30) | (5 << 56) | (1 << 60), 46),
    "Pulsing": ("pulsing", 0x07, 9, (5 << 24) | (2 << 28) | (100 << 30) | (5 << 56) | (1 << 60), 46),
    "Welding": ("welding", 0x07, 10, (18 << 21) | (2 << 28) | (100 << 30) | (5 << 56) | (1 << 60), 46),
    "Cop car": ("cop_car", 0x07, 11, (2 << 46) | (5 << 50), 54),
    "Color chase": ("color_chase", 0x07, 12, (100 << 43) | (5 << 50), 54),
    "Party lights": ("party_lights", 0x07, 13, (100 << 43) | (5 << 50), 54),
    "Fireworks": ("fireworks", 0x07, 14, 5 << 50, 54),
    # Second-generation presets use Kelvin/50 for their HSI white point.
    # Paparazzi/Welding II have a separate intensity packet (bit = -1 here).
    "Paparazzi II": ("paparazzi_2", 0x22, 0, (112 << 33) | (100 << 42) | (1 << 49) | (1 << 58) | (1 << 61), -1),
    "Lightning II": ("lightning_2", 0x22, 1, (112 << 16) | (100 << 25) | (1 << 32) | (1 << 41) | (5 << 44) | (5 << 48), 52),
    "TV II": ("tv_2", 0x22, 2, (112 << 11) | (100 << 20) | (1 << 27) | (180 << 36) | (1 << 45) | (5 << 48), 52),
    "Fire II": ("fire_2", 0x22, 3, (112 << 11) | (100 << 20) | (1 << 27) | (180 << 36) | (1 << 45) | (5 << 48), 52),
    "Strobe II": ("strobe_2", 0x22, 4, (112 << 20) | (100 << 29) | (1 << 36) | (1 << 45) | (5 << 48), 52),
    "Explosion II": ("explosion_2", 0x22, 5, (112 << 20) | (100 << 29) | (1 << 36) | (1 << 45) | (5 << 48), 52),
    "Faulty bulb II": ("faulty_bulb_2", 0x22, 6, (112 << 16) | (100 << 25) | (1 << 32) | (1 << 41) | (5 << 44) | (5 << 48), 52),
    "Pulsing II": ("pulsing_2", 0x22, 7, (112 << 16) | (100 << 25) | (1 << 32) | (1 << 41) | (5 << 44) | (5 << 48), 52),
    "Welding II": ("welding_2", 0x22, 8, (100 << 42) | (1 << 49) | (1 << 58) | (1 << 61), -1),
    "Cop car II": ("cop_car_2", 0x22, 9, (4 << 45) | (5 << 48), 52),
    "Party lights II": ("party_lights_2", 0x22, 10, (5 << 36) | (100 << 42), 52),
    "Fireworks II": ("fireworks_2", 0x22, 11, (20 << 34) | (60 << 43), 52),
    # Gen III's SDK supplies packers but no high-level defaults. These test
    # presets reuse the II HSI palette/gaps; physical behavior needs validation.
    "Lightning III": ("lightning_3", 0x22, 12, (112 << 33) | (100 << 42) | (1 << 49) | (1 << 58) | (1 << 61), -1),
    "TV III": ("tv_3", 0x22, 13, (112 << 24) | (100 << 33) | (1 << 40) | (180 << 49) | (1 << 58) | (1 << 61), -1),
    "Fire III": ("fire_3", 0x22, 14, (112 << 24) | (100 << 33) | (1 << 40) | (180 << 49) | (1 << 58) | (1 << 61), -1),
    "Faulty bulb III": ("faulty_bulb_3", 0x22, 15, (112 << 33) | (100 << 42) | (1 << 49) | (1 << 58) | (1 << 61), -1),
    "Pulsing III": ("pulsing_3", 0x22, 16, (112 << 16) | (100 << 25) | (1 << 32) | (1 << 41) | (5 << 44), 52),
    "Cop car III": ("cop_car_3", 0x22, 17, (2 << 45) | (5 << 48), 52),
}


def effect_values(name: str, intensity: int, *, stop: bool = False) -> list[int]:
    """Return the 80-bit setter before its checksum is added."""

    if name == "off":
        return [(0x87 << 72) | (15 << 64)]
    _, command, effect_id, defaults, intensity_bit = EFFECTS[name]
    if stop and command == 0x07:
        return effect_values("off", 0)
    intensity = max(0, min(1000, intensity))
    header = ((command | 0x80) << 72) | (effect_id << 64)
    state = 1 << (8 if command == 0x07 else 62)
    value = header | defaults | (0 if stop else state)
    if intensity_bit >= 0:
        return [value | (intensity << intensity_bit)]
    # The app stages intensity with state=3, then commits color with state=1.
    if effect_id == 8:
        parameters = (5 << 37) | (min(180, intensity) << 41)
    elif effect_id == 14:
        parameters = 5 << 43
    else:
        parameters = (20 << 33) | (60 << 42)
    staged = header | parameters | (intensity << 51) | (3 << 62)
    return [staged, value]


def decode_effect(value: int) -> tuple[str, int] | None:
    """Read the selected preset and intensity; color-mode variants stay assumed."""

    command = (value >> 72) & 0x7F
    effect_id = (value >> 64) & 0xFF
    if command == 0x07 and effect_id == 15:
        return "off", 0
    for name, (_, candidate, candidate_id, _, intensity_bit) in EFFECTS.items():
        if command != candidate or effect_id != candidate_id:
            continue
        if command == 0x22 and (value >> 62) & 3 == 0:
            return "off", 0
        if intensity_bit < 0 or (command == 0x22 and (value >> 62) & 3 != 1):
            # Never mark a multipart or stopped effect confirmed from half a report.
            return None
        if command == 0x07 and 6 <= effect_id <= 10 and (value >> 60) & 0xF != 1:
            return None
        return name, (value >> intensity_bit) & 0x3FF
    return None
