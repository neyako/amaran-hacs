"""Parity checks between HA command planning and the standalone POC."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from custom_components.amaran.commands import (
    brightness_payloads,
    brightness_cct_payloads,
    cct_payloads,
    hsi_payloads,
    power_off_payloads,
)
from custom_components.amaran.protocol import build_mesh_proxy_pdu, hsi_payload
from scripts.amaran_ace25c_poc import _build_commands

NET_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
APP_KEY = bytes.fromhex("ffeeddccbbaa99887766554433221100")
SRC = 0x000F
DST = 0x000B
SEQ = 100000
IV_INDEX = 0
TTL = 7


def _poc_payloads(
    *, power: str | None = None, brightness: int | None = None, cct: int | None = None
) -> list[bytes]:
    args = SimpleNamespace(power=power, brightness=brightness, cct=cct, gm=0)
    return [payload for _, payload in _build_commands(args)]


def _proxy_pdus(payloads: list[bytes]) -> list[bytes]:
    return [
        build_mesh_proxy_pdu(
            net_key=NET_KEY,
            app_key=APP_KEY,
            src=SRC,
            dst=DST,
            seq=SEQ + index,
            iv_index=IV_INDEX,
            sidus_payload=payload,
            ttl=TTL,
        )
        for index, payload in enumerate(payloads)
    ]


class PocParityTest(unittest.TestCase):
    """HA may translate state, but emitted packets must match the POC."""

    def test_turn_on_restore_packets_match_poc(self) -> None:
        ha_payloads = cct_payloads(
            brightness=51,
            kelvin=3200,
            power_on=True,
        )
        poc_payloads = _poc_payloads(power="on", brightness=20, cct=3200)

        self.assertEqual(ha_payloads, poc_payloads)
        self.assertEqual(_proxy_pdus(ha_payloads), _proxy_pdus(poc_payloads))

    def test_brightness_change_uses_poc_brightness_packet(self) -> None:
        ha_payloads = brightness_payloads(brightness=204)
        poc_payloads = _poc_payloads(brightness=80)

        self.assertEqual(ha_payloads, poc_payloads)
        self.assertNotEqual(ha_payloads, _poc_payloads(brightness=80, cct=6500))

    def test_cct_change_preserves_brightness_in_poc_packet(self) -> None:
        ha_payloads = cct_payloads(brightness=153, kelvin=5600)
        poc_payloads = _poc_payloads(brightness=60, cct=5600)

        self.assertEqual(ha_payloads, poc_payloads)

    def test_hsi_change_uses_reference_hsi_packet(self) -> None:
        self.assertEqual(
            hsi_payloads(brightness=204, hue=45, saturation=60),
            [hsi_payload(hue=45, saturation=60, intensity=800)],
        )

    def test_legacy_brightness_cct_wrapper_still_maps_to_cct_packet(self) -> None:
        self.assertEqual(
            brightness_cct_payloads(brightness=153, kelvin=5600),
            cct_payloads(brightness=153, kelvin=5600),
        )

    def test_power_off_packet_matches_poc(self) -> None:
        self.assertEqual(power_off_payloads(), _poc_payloads(power="off"))


if __name__ == "__main__":
    unittest.main()
