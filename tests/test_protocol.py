"""Regression tests for Sidus command payloads."""

import unittest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from custom_components.amaran.const import PROXY_FILTER_TYPE_REJECT
from custom_components.amaran.protocol import (
    access_payload,
    brightness_payload_percent,
    build_proxy_filter_pdu,
    cct_payload_percent,
    decode_mesh_proxy_access,
    decode_sidus_power_info_payload,
    decode_sidus_status_payload,
    derive_mesh_keys,
    hsi_payload,
    hsi_payload_ha,
    rgb_payload_ha,
    effect_payloads_ha,
    is_proxy_filter_status,
    power_payload,
    power_status_request_payload,
    sidus_checksum,
    status_request_payload,
    build_mesh_proxy_pdu,
)

NET_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
APP_KEY = bytes.fromhex("ffeeddccbbaa99887766554433221100")


class DeriveMeshKeysCacheTest(unittest.TestCase):
    """derive_mesh_keys must memoize per (net_key, app_key)."""

    def test_same_keys_return_cached_instance(self) -> None:
        first = derive_mesh_keys(NET_KEY, APP_KEY)
        second = derive_mesh_keys(NET_KEY, APP_KEY)
        # Cache hit returns the identical object, not just an equal one.
        self.assertIs(first, second)

    def test_different_keys_derive_distinct_values(self) -> None:
        a = derive_mesh_keys(NET_KEY, APP_KEY)
        b = derive_mesh_keys(APP_KEY, NET_KEY)
        self.assertIsNot(a, b)
        self.assertNotEqual(
            (a.nid, a.encryption_key, a.privacy_key, a.aid),
            (b.nid, b.encryption_key, b.privacy_key, b.aid),
        )


class PowerPayloadTest(unittest.TestCase):
    """Power payload capture regressions."""

    def test_power_payload_turn_on_matches_official_app_capture(self) -> None:
        """HA turn_on must emit the official app's turn-on Sidus payload."""

        self.assertEqual(power_payload(True), bytes.fromhex("8d00000000000000018c"))

    def test_power_payload_turn_off_matches_official_app_capture(self) -> None:
        """HA turn_off must emit the official app's turn-off Sidus payload."""

        self.assertEqual(power_payload(False), bytes.fromhex("8c00000000000000008c"))


class BrightnessPayloadTest(unittest.TestCase):
    """Brightness payload parity with wesbos/amaran-BLE-control."""

    def test_brightness_10_percent_matches_poc_capture(self) -> None:
        self.assertEqual(
            brightness_payload_percent(10),
            bytes.fromhex("a800000000000000198f"),
        )

    def test_brightness_50_percent_matches_poc_capture(self) -> None:
        self.assertEqual(
            brightness_payload_percent(50),
            bytes.fromhex("0c000000000000007d8f"),
        )


class RgbPayloadTest(unittest.TestCase):
    def test_ace_truncated_rgb_captures_do_not_confirm_black(self) -> None:
        for capture in ("ab610600000000400004", "7b610600000010000004", "6f610600000400000004"):
            status = decode_sidus_status_payload(
                bytes.fromhex(capture), source_address=11, destination_address=1, sequence=1,
            )
            self.assertTrue(status.power)
            self.assertEqual(status.brightness, 26)
            self.assertEqual(status.color_mode, "rgb")
            self.assertIsNone(status.rgb_color)

    def test_rgb_matches_app_scaling_layout_and_report(self) -> None:
        payload = rgb_payload_ha(rgb_color=(255, 128, 1), brightness=128)
        value = int.from_bytes(payload, "little")
        self.assertEqual(payload[9], 0x84)
        self.assertEqual(payload[0], sidus_checksum(payload))
        self.assertEqual((value >> 8) & 0xF, 1)
        self.assertEqual((value >> 12) & 0x3FF, 502)
        self.assertEqual((value >> 22) & 0xFFFFF, 0)
        self.assertEqual([(value >> shift) & 0x3FF for shift in (62, 52, 42)], [1000, 502, 4])
        report = bytearray(payload)
        report[9] = 0x04
        report[0] = sidus_checksum(report)
        status = decode_sidus_status_payload(bytes(report), source_address=11, destination_address=1, sequence=1)
        self.assertEqual(status.rgb_color, (255, 128, 1))
        self.assertEqual(status.brightness, 128)
        self.assertEqual(status.color_mode, "rgb")
        # A white-channel report cannot truthfully be represented as native RGB.
        report[3] |= 1
        report[0] = sidus_checksum(report)
        self.assertIsNone(decode_sidus_status_payload(bytes(report), source_address=11, destination_address=1, sequence=2))


class EffectPayloadTest(unittest.TestCase):
    def test_presets_match_compiled_java_sdk_vectors(self) -> None:
        # Offline getSendData() output from Protocol2/3 classes, not light captures.
        # Gen III uses our documented test presets; II uses app Effect defaults.
        vectors = {
            "Paparazzi II": "D900000028F040DF00A2 79000000E090036400A2",
            "Lightning II": "310070C80152857E01A2",
            "TV II": "E380430E402B857E02A2",
            "Fire II": "E480430E402B857E03A2",
            "Strobe II": "6C0000871C20857E04A2",
            "Explosion II": "6D0000871C20857E05A2",
            "Faulty bulb II": "360070C80152857E06A2",
            "Pulsing II": "370070C80152857E07A2",
            "Welding II": "D2000000A06841DF08A2 A10000000090036408A2",
            "Cop car II": "2E0000000080857E09A2",
            "Party lights II": "8B0000005090817E0AA2",
            "Fireworks II": "DC00000050E0817E0BA2",
            "Lightning III": "E500000028F040DF0CA2 85000000E09003640CA2",
            "TV III": "E600000028F040DF0DA2 B5000070C80168650DA2",
            "Fire III": "F7000000002840DF0EA2 B6000070C80168650EA2",
            "Faulty bulb III": "E800000028F040DF0FA2 88000000E09003640FA2",
            "Pulsing III": "3B0070C80152807E10A2",
            "Cop car III": "F60000000040857E11A2",
        }
        for name, expected in vectors.items():
            with self.subTest(effect=name):
                self.assertEqual(
                    effect_payloads_ha(effect=name, brightness=255),
                    [bytes.fromhex(packet) for packet in expected.split()],
                )

    def test_base_effect_defaults_and_off_match_sdk(self) -> None:
        from custom_components.amaran.effects import EFFECTS

        for effect in EFFECTS:
            with self.subTest(effect=effect):
                payload = effect_payloads_ha(effect=effect, brightness=128)[-1]
                self.assertEqual(payload[0], sidus_checksum(payload))
                status = decode_sidus_status_payload(payload, source_address=11, destination_address=1, sequence=1)
                if EFFECTS[effect][4] < 0:
                    self.assertIsNone(status)
                    continue
                self.assertTrue(status.power)
                self.assertEqual(status.effect, effect)
                self.assertEqual(status.brightness, 128)
        candle = effect_payloads_ha(effect="Candle", brightness=255)[0]
        value = int.from_bytes(candle, "little")
        self.assertEqual(candle[8:], bytes([4, 0x87]))
        self.assertEqual((value >> 40) & 0x3FF, 0)  # SDK cct_type, not kelvin
        self.assertEqual((value >> 50) & 0xF, 5)
        self.assertEqual((value >> 54) & 0x3FF, 1000)
        self.assertEqual(effect_payloads_ha(effect="off", brightness=0)[0].hex(), "96000000000000000f87")

    def test_unimplemented_effect_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            effect_payloads_ha(effect="Made up", brightness=255)

    def test_multipart_staging_and_generation_specific_stops(self) -> None:
        for name, effect_id in (("Paparazzi II", 0), ("Welding II", 8), ("Lightning III", 12), ("TV III", 13), ("Fire III", 14), ("Faulty bulb III", 15)):
            with self.subTest(name=name):
                payloads = effect_payloads_ha(effect=name, brightness=26)
                self.assertEqual(len(payloads), 2)
                staged, active = (int.from_bytes(p, "little") for p in payloads)
                self.assertEqual((staged >> 61) & 7, 6)  # package 0, state 3
                self.assertEqual((active >> 61) & 7, 3)  # package 1, state 1
                self.assertEqual((staged >> 51) & 1023, 102)
                self.assertEqual(payloads[-1][8:], bytes([effect_id, 0xA2]))
                stopped = effect_payloads_ha(effect=name, brightness=26, stop=True)[-1]
                self.assertEqual((int.from_bytes(stopped, "little") >> 62) & 3, 0)
                report = decode_sidus_status_payload(stopped, source_address=11, destination_address=1, sequence=1)
                self.assertEqual(report.color_mode, "effect_off")
                self.assertIsNone(report.power)
                self.assertIsNone(report.brightness)
        off = decode_sidus_status_payload(effect_payloads_ha(effect="off", brightness=255)[0], source_address=11, destination_address=1, sequence=1)
        self.assertEqual(off.color_mode, "effect_off")


class CctPayloadTest(unittest.TestCase):
    """CCT payload parity with wesbos/amaran-BLE-control."""

    def test_cct_3200k_22_percent_matches_poc_capture(self) -> None:
        self.assertEqual(
            cct_payload_percent(percent=22, kelvin=3200),
            bytes.fromhex("0e000000004001143782"),
        )

    def test_cct_5600k_30_percent_matches_poc_capture(self) -> None:
        self.assertEqual(
            cct_payload_percent(percent=30, kelvin=5600),
            bytes.fromhex("31000000004001234b82"),
        )

    def test_cct_payload_gm_zero_matches_neutral_capture(self) -> None:
        self.assertEqual(
            cct_payload_percent(percent=30, kelvin=5600, gm=0),
            bytes.fromhex("31000000004001234b82"),
        )

    def test_cct_payload_gm_offset_changes_bytes(self) -> None:
        neutral = cct_payload_percent(percent=30, kelvin=5600, gm=0)
        green = cct_payload_percent(percent=30, kelvin=5600, gm=5)
        magenta = cct_payload_percent(percent=30, kelvin=5600, gm=-5)

        self.assertNotEqual(green, neutral)
        self.assertNotEqual(magenta, neutral)
        self.assertNotEqual(green, magenta)

    def test_cct_signed_tint_matches_requested_offset(self) -> None:
        for gm in (-10, -5, -1, 0, 5, 10):
            with self.subTest(gm=gm):
                payload = cct_payload_percent(percent=30, kelvin=5600, gm=gm)
                encoded = (int.from_bytes(payload, "little") >> 45) & 0x7F
                self.assertEqual(encoded - 10, gm)

    def test_cct_status_decode_ignores_gm(self) -> None:
        status = decode_sidus_status_payload(
            cct_payload_percent(percent=30, kelvin=5600, gm=7),
            source_address=0x000B,
            destination_address=0x000F,
            sequence=1,
        )

        self.assertIsNotNone(status)
        self.assertEqual(status.color_temp_kelvin, 5600)
        self.assertEqual(status.color_mode, "color_temp")

    def test_cct_6500k_80_percent_matches_reference(self) -> None:
        self.assertEqual(
            cct_payload_percent(percent=80, kelvin=6500),
            bytes.fromhex("530000000040a128c882"),
        )


class HsiPayloadTest(unittest.TestCase):
    """HSI payload parity with wesbos/amaran-BLE-control."""

    def test_hsi_matches_reference(self) -> None:
        self.assertEqual(
            hsi_payload(hue=45, saturation=60, intensity=800),
            bytes.fromhex("fd0000000000af05c881"),
        )

    def test_hsi_payload_ha_matches_reference_scale(self) -> None:
        self.assertEqual(
            hsi_payload_ha(hue=45, saturation=60, brightness=204),
            bytes.fromhex("fd0000000000af05c881"),
        )


class AccessPayloadTest(unittest.TestCase):
    """Access opcode regressions."""

    def test_access_payload_uses_telink_opcode(self) -> None:
        self.assertEqual(
            access_payload(power_payload(True)),
            bytes.fromhex("268d00000000000000018c"),
        )


class StatusPayloadTest(unittest.TestCase):
    def test_status_request_payload_matches_telink_reference(self) -> None:
        self.assertEqual(
            status_request_payload(),
            bytes.fromhex("0e00000000000000000e"),
        )

    def test_power_status_request_payload_matches_sdk_capture(self) -> None:
        self.assertEqual(
            power_status_request_payload(),
            bytes.fromhex("0a00000000000000000a"),
        )

    def test_decode_power_info_payload_matches_sdk_bitfields(self) -> None:
        payload = _power_info_payload(
            power_state=0,
            battery_time=34,
            battery_percentage=53,
            battery_voltage=7420,
            external_voltage=0,
        )

        power_info = decode_sidus_power_info_payload(
            payload,
            source_address=0x000B,
            destination_address=0x000F,
            sequence=42,
        )

        self.assertIsNotNone(power_info)
        self.assertEqual(power_info.power_supply_mode, "battery")
        self.assertEqual(power_info.battery_time_minutes, 34)
        self.assertEqual(power_info.battery_percentage, 53)
        self.assertEqual(power_info.battery_voltage, 7420)
        self.assertEqual(power_info.external_voltage, 0)
        self.assertEqual(power_info.command_type, 0x0A)

    def test_decode_power_info_payload_handles_ac_mode(self) -> None:
        payload = _power_info_payload(
            power_state=1,
            battery_time=120,
            battery_percentage=100,
            battery_voltage=0,
            external_voltage=24000,
        )

        power_info = decode_sidus_power_info_payload(
            payload,
            source_address=0x0004,
            destination_address=0x000F,
            sequence=43,
        )

        self.assertIsNotNone(power_info)
        self.assertEqual(power_info.power_supply_mode, "ac")
        self.assertEqual(power_info.battery_time_minutes, 120)
        self.assertEqual(power_info.battery_percentage, 100)
        self.assertEqual(power_info.external_voltage, 24000)

    def test_decode_power_info_rejects_bad_checksum(self) -> None:
        payload = bytearray(
            _power_info_payload(
                power_state=1,
                battery_time=34,
                battery_percentage=53,
                battery_voltage=7420,
                external_voltage=0,
            )
        )
        payload[0] ^= 0xFF

        self.assertIsNone(
            decode_sidus_power_info_payload(
                bytes(payload),
                source_address=0x000B,
                destination_address=0x000F,
                sequence=42,
            )
        )

    def test_decode_cct_status_payload(self) -> None:
        status = decode_sidus_status_payload(
            cct_payload_percent(percent=30, kelvin=5600),
            source_address=0x000B,
            destination_address=0x000F,
            sequence=42,
        )

        self.assertIsNotNone(status)
        self.assertEqual(status.brightness, 77)
        self.assertEqual(status.color_temp_kelvin, 5600)
        self.assertEqual(status.color_mode, "color_temp")

    def test_decode_hsi_status_payload(self) -> None:
        status = decode_sidus_status_payload(
            hsi_payload(hue=45, saturation=60, intensity=800),
            source_address=0x000B,
            destination_address=0x000F,
            sequence=42,
        )

        self.assertIsNotNone(status)
        self.assertEqual(status.brightness, 204)
        self.assertEqual(status.hs_color, (45.0, 60.0))
        self.assertEqual(status.color_mode, "hs")

    def test_decode_mesh_proxy_access_status(self) -> None:
        proxy_pdu = build_mesh_proxy_pdu(
            net_key=NET_KEY,
            app_key=APP_KEY,
            src=0x000B,
            dst=0x000F,
            seq=42,
            iv_index=0,
            sidus_payload=hsi_payload(hue=45, saturation=60, intensity=800),
            ttl=7,
        )

        decoded = decode_mesh_proxy_access(
            net_key=NET_KEY,
            app_key=APP_KEY,
            iv_index=0,
            proxy_pdu=proxy_pdu,
        )

        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.source_address, 0x000B)
        self.assertEqual(decoded.destination_address, 0x000F)
        self.assertIsNotNone(decoded.sidus_status)
        self.assertEqual(decoded.sidus_status.hs_color, (45.0, 60.0))

    def test_invalid_mesh_authentication_is_dropped(self) -> None:
        packet = bytearray(build_mesh_proxy_pdu(
            net_key=NET_KEY, app_key=APP_KEY, src=11, dst=15, seq=42,
            iv_index=0, sidus_payload=hsi_payload(hue=45, saturation=60, intensity=800),
        ))
        packet[-1] ^= 1
        self.assertIsNone(decode_mesh_proxy_access(
            net_key=NET_KEY, app_key=APP_KEY, iv_index=0, proxy_pdu=bytes(packet),
        ))

    def test_decode_mesh_proxy_access_power_info(self) -> None:
        proxy_pdu = build_mesh_proxy_pdu(
            net_key=NET_KEY,
            app_key=APP_KEY,
            src=0x000B,
            dst=0x000F,
            seq=42,
            iv_index=0,
            sidus_payload=_power_info_payload(
                power_state=1,
                battery_time=34,
                battery_percentage=53,
                battery_voltage=7420,
                external_voltage=0,
            ),
            ttl=7,
        )

        decoded = decode_mesh_proxy_access(
            net_key=NET_KEY,
            app_key=APP_KEY,
            iv_index=0,
            proxy_pdu=proxy_pdu,
        )

        self.assertIsNotNone(decoded)
        self.assertIsNotNone(decoded.sidus_power_info)
        self.assertEqual(decoded.sidus_power_info.battery_percentage, 53)


class ProxyFilterTest(unittest.TestCase):
    """Bluetooth Mesh proxy filter PDU (Mesh Profile 6.5) regressions."""

    def test_set_filter_reject_pdu_round_trips(self) -> None:
        pdu = build_proxy_filter_pdu(
            net_key=NET_KEY, app_key=APP_KEY, src=0x000F, seq=100, iv_index=0
        )
        # Proxy PDU type 0x02 = Proxy Configuration.
        self.assertTrue(is_proxy_filter_status(pdu))
        ctl_ttl, seq, src, dst, config = _decrypt_proxy_filter(pdu)
        self.assertEqual(ctl_ttl, 0x80)  # CTL=1, TTL=0
        self.assertEqual(seq, 100)
        self.assertEqual(src, 0x000F)
        self.assertEqual(dst, 0x0000)
        self.assertEqual(config, bytes([0x00, PROXY_FILTER_TYPE_REJECT]))

    def test_add_addresses_pdu_round_trips(self) -> None:
        pdu = build_proxy_filter_pdu(
            net_key=NET_KEY,
            app_key=APP_KEY,
            src=0x000F,
            seq=5,
            iv_index=0,
            addresses=(0x000F, 0xC000),
        )
        _ctl, _seq, _src, _dst, config = _decrypt_proxy_filter(pdu)
        self.assertEqual(config, bytes([0x01, 0x00, 0x0F, 0xC0, 0x00]))

    def test_is_proxy_filter_status_distinguishes_pdu_type(self) -> None:
        self.assertTrue(is_proxy_filter_status(b"\x02\x03\x01\x00\x00"))
        self.assertFalse(is_proxy_filter_status(b"\x00\x01\x02"))
        self.assertFalse(is_proxy_filter_status(b""))


def _decrypt_proxy_filter(pdu: bytes, iv_index: int = 0) -> tuple:
    """Reverse build_proxy_filter_pdu to validate its structure."""

    keys = derive_mesh_keys(NET_KEY, APP_KEY)
    network_pdu = pdu[1:]
    iv_bytes = iv_index.to_bytes(4, "big")
    obfuscated = network_pdu[1:7]
    encrypted = network_pdu[7:]
    ecb = Cipher(algorithms.AES(keys.privacy_key), modes.ECB()).encryptor()
    pecb = ecb.update(b"\x00" * 5 + iv_bytes + encrypted[:7]) + ecb.finalize()
    clear = bytes(obfuscated[i] ^ pecb[i] for i in range(6))
    ctl_ttl = clear[0]
    seq = int.from_bytes(clear[1:4], "big")
    src = int.from_bytes(clear[4:6], "big")
    proxy_nonce = b"\x03\x00" + clear[1:4] + clear[4:6] + b"\x00\x00" + iv_bytes
    plaintext = AESCCM(keys.encryption_key, tag_length=8).decrypt(
        proxy_nonce, encrypted, None
    )
    dst = int.from_bytes(plaintext[:2], "big")
    return ctl_ttl, seq, src, dst, plaintext[2:]


def _power_info_payload(
    *,
    power_state: int,
    battery_time: int,
    battery_percentage: int,
    battery_voltage: int,
    external_voltage: int,
) -> bytes:
    payload = bytearray(10)
    payload[2] = (int(power_state) & 0x01) << 7
    payload[3] = int(battery_time) & 0xFF
    payload[4] = ((int(battery_time) >> 8) & 0x01) | (
        (int(battery_percentage) & 0x7F) << 1
    )
    payload[5] = int(battery_voltage) & 0xFF
    payload[6] = (int(battery_voltage) >> 8) & 0xFF
    payload[7] = int(external_voltage) & 0xFF
    payload[8] = (int(external_voltage) >> 8) & 0xFF
    payload[9] = 0x0A
    payload[0] = sidus_checksum(payload)
    return bytes(payload)
