"""Regression tests for Sidus command payloads."""

import unittest

from custom_components.amaran.protocol import (
    access_payload,
    brightness_payload_percent,
    cct_payload_percent,
    decode_mesh_proxy_access,
    decode_sidus_status_payload,
    hsi_payload,
    hsi_payload_ha,
    power_payload,
    status_request_payload,
    build_mesh_proxy_pdu,
)

NET_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
APP_KEY = bytes.fromhex("ffeeddccbbaa99887766554433221100")


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

    def test_cct_6500k_80_percent_matches_reference(self) -> None:
        self.assertEqual(
            cct_payload_percent(percent=80, kelvin=6500),
            bytes.fromhex("530000000040a128c882"),
        )


class HsiPayloadTest(unittest.TestCase):
    """HSI/RGB payload parity with wesbos/amaran-BLE-control."""

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
