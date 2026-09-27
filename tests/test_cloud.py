"""amaran account sign-in tests."""

from __future__ import annotations

import asyncio
import unittest

from custom_components.amaran.cloud import (
    CloudAuthError,
    async_fetch_import_payload,
    region_url,
)
from custom_components.amaran.fixtures import load_fixture_import_payload

NET_KEY = "00112233445566778899AABBCCDDEEFF"
APP_KEY = "FFEEDDCCBBAA99887766554433221100"
LIGHT_LIST = {
    "code": 20000,
    "data": {
        "meshs": {
            "existing": [
                {"mesh_uuid": "MESH1", "net_key": NET_KEY, "app_key": APP_KEY}
            ],
            "deleted": [],
        },
        "fixtures": {
            "existing": [
                {
                    "mesh_uuid": "MESH1",
                    "name": "amaran T4c  #1",
                    "code": "40095",
                    "mac_address": "70:3E:97:B1:B7:2E",
                    "node_address": 13,
                },
                {
                    "mesh_uuid": "GONE",
                    "name": "Old light",
                    "code": "400U5",
                    "mac_address": "A4:C1:38:00:00:01",
                    "node_address": 3,
                },
            ],
        },
    },
}


class CloudTest(unittest.TestCase):
    def test_region_follows_country(self) -> None:
        self.assertEqual(region_url("de"), "https://eu.sidus.link/")
        self.assertEqual(region_url("TW"), "https://cn.sidus.link/")
        self.assertEqual(region_url("VN"), "https://us.sidus.link/")
        self.assertEqual(region_url(None), "https://us.sidus.link/")

    def test_sign_in_follows_region_redirect_and_imports_lights(self) -> None:
        session = FakeSession(
            [
                {"code": 4001, "data": {"OtherRegionUser": [{"area": "DE"}]}},
                {"code": 20000, "data": {"token": "TOKEN"}},
                LIGHT_LIST,
            ]
        )

        payload = asyncio.run(
            async_fetch_import_payload(session, "me@example.com", "secret", "US")
        )
        imported = load_fixture_import_payload(payload, source="account")

        self.assertEqual(
            [(method, url) for method, url, _ in session.calls],
            [
                ("post", "https://us.sidus.link/uc/user/login"),
                ("post", "https://eu.sidus.link/uc/user/login"),
                ("get", "https://eu.sidus.link/amaran/pack/query"),
            ],
        )
        self.assertEqual(session.calls[1][2]["json"]["area"], "DE")
        self.assertEqual(session.calls[1][2]["headers"]["request_source"], "4")
        self.assertEqual(session.calls[2][2]["headers"]["Token"], "TOKEN")
        [light] = imported.fixtures
        self.assertEqual(light["name"], "amaran T4c #1")
        self.assertEqual(light["node_address"], 13)
        self.assertEqual(light["net_key"], NET_KEY.lower())
        self.assertIn("hs", light["supported_color_modes"])

    def test_wrong_password_is_auth_error(self) -> None:
        session = FakeSession([{"code": 20002, "data": None}])

        with self.assertRaises(CloudAuthError):
            asyncio.run(async_fetch_import_payload(session, "0901234567", "x", "VN"))
        self.assertEqual(session.calls[0][2]["json"]["phone_number"], "0901234567")


class FakeSession:
    def __init__(self, replies: list[dict]) -> None:
        self._replies = replies
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse(self._replies.pop(0))


class FakeResponse:
    def __init__(self, reply: dict) -> None:
        self._reply = reply

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def json(self, content_type=None) -> dict:
        return self._reply


if __name__ == "__main__":
    unittest.main()
