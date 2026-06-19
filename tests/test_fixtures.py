"""Fixture import and capability detection tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import tempfile
import unittest

from custom_components.amaran.const import (
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_HS,
    CONF_ADDRESS,
    CONF_BATTERY_CAPABLE,
    CONF_BLE_MAC,
    CONF_PRODUCT_ID,
    CONF_MODEL,
    CONF_NAME,
    CONF_NODE_ADDRESS,
    CONF_SUPPORTED_COLOR_MODES,
)
from custom_components.amaran.fixtures import (
    detect_fixture_profile,
    fixture_unique_id,
    is_battery_capable_light,
    light_capability_names,
    load_fixture_import,
    load_fixture_import_json,
    supported_color_modes_for_fixture,
)
from custom_components.amaran.redaction import REDACTED, redact_sensitive

NET_KEY = "00112233445566778899aabbccddeeff"
APP_KEY = "ffeeddccbbaa99887766554433221100"


class FixtureImportTest(unittest.TestCase):
    def test_db_imports_multiple_supported_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "amaran.db"
            _write_db(db_path)

            imported = load_fixture_import(db_path)

        self.assertEqual(len(imported.fixtures), 5)
        self.assertEqual(len(imported.skipped), 0)
        names = {fixture[CONF_NAME] for fixture in imported.fixtures}
        self.assertEqual(
            names,
            {
                "amaran 100x S #1",
                "amaran 60x S #1",
                "amaran Ace 25c #1",
                "amaran Pano 60c #1",
                "Unknown fixture",
            },
        )
        by_model = {fixture[CONF_MODEL]: fixture for fixture in imported.fixtures}
        self.assertEqual(
            by_model["amaran 100x S"][CONF_SUPPORTED_COLOR_MODES],
            [COLOR_MODE_COLOR_TEMP],
        )
        self.assertEqual(
            by_model["amaran 60x S"][CONF_SUPPORTED_COLOR_MODES],
            [COLOR_MODE_COLOR_TEMP],
        )
        self.assertEqual(
            by_model["amaran Ace 25c"][CONF_SUPPORTED_COLOR_MODES],
            [COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS],
        )
        self.assertEqual(
            by_model["amaran Pano 60c"][CONF_SUPPORTED_COLOR_MODES],
            [COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS],
        )
        self.assertEqual(by_model["amaran Ace 25c"][CONF_NODE_ADDRESS], 11)
        self.assertEqual(by_model["amaran Ace 25c"][CONF_BLE_MAC], "AA:BB:CC:DD:EE:01")
        self.assertEqual(
            by_model["Unknown fixture"][CONF_SUPPORTED_COLOR_MODES],
            [COLOR_MODE_COLOR_TEMP],
        )

    def test_wesbos_json_export_imports_supported_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "lights.json"
            json_path.write_text(
                json.dumps(
                    {
                        "netKey": NET_KEY,
                        "appKey": APP_KEY,
                        "lights": [
                            {
                                "name": "Key Light",
                                "mac": "AA:BB:CC:DD:EE:01",
                                "address": 11,
                                "model": "Ace 25c",
                            },
                            {
                                "name": "Halo 100x",
                                "mac": "AA:BB:CC:DD:EE:04",
                                "address": 2,
                            },
                        ],
                    }
                )
            )

            imported = load_fixture_import(json_path)

        self.assertEqual(len(imported.fixtures), 2)
        self.assertEqual(
            imported.fixtures[0][CONF_SUPPORTED_COLOR_MODES],
            [COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS],
        )
        self.assertEqual(
            imported.fixtures[1][CONF_SUPPORTED_COLOR_MODES],
            [COLOR_MODE_COLOR_TEMP],
        )

    def test_db_product_id_takes_precedence_over_hex_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "amaran.db"
            _write_db_with_product_id(db_path)

            imported = load_fixture_import(db_path)

        self.assertEqual(len(imported.fixtures), 1)
        self.assertEqual(imported.fixtures[0][CONF_PRODUCT_ID], 91)
        self.assertEqual(imported.fixtures[0][CONF_MODEL], "amaran Ace 25c")
        self.assertEqual(
            imported.fixtures[0][CONF_SUPPORTED_COLOR_MODES],
            [COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS],
        )

    def test_paste_json_import_creates_multiple_fixtures(self) -> None:
        imported = load_fixture_import_json(
            json.dumps(
                {
                    "net_key": NET_KEY,
                    "app_key": APP_KEY,
                    "fixtures": [
                        {
                            "name": "Ace",
                            "mac_address": "AA:BB:CC:DD:EE:01",
                            "node_address": 11,
                            "model": "Ace 25c",
                        },
                        {
                            "name": "Unknown RGB",
                            "mac_address": "AA:BB:CC:DD:EE:05",
                            "node_address": 12,
                            "model": "Mystery",
                            "capabilities": ["rgb"],
                        },
                    ],
                }
            )
        )

        self.assertEqual(len(imported.fixtures), 2)
        self.assertEqual(
            imported.fixtures[0][CONF_SUPPORTED_COLOR_MODES],
            [COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS],
        )
        self.assertEqual(
            imported.fixtures[1][CONF_SUPPORTED_COLOR_MODES],
            [COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS],
        )

    def test_paste_json_import_skips_motorized_accessory(self) -> None:
        imported = load_fixture_import_json(
            json.dumps(
                {
                    "net_key": NET_KEY,
                    "app_key": APP_KEY,
                    "fixtures": [
                        {
                            "name": "Ace",
                            "mac_address": "AA:BB:CC:DD:EE:01",
                            "node_address": 11,
                            "model": "Ace 25c",
                        },
                        {
                            "name": "Yoke",
                            "mac_address": "AA:BB:CC:DD:EE:02",
                            "node_address": 12,
                            "model": "Motorized Yoke",
                        },
                    ],
                }
            )
        )

        self.assertEqual(len(imported.fixtures), 1)
        self.assertEqual(imported.fixtures[0][CONF_NAME], "Ace")
        self.assertEqual(
            imported.skipped,
            [{"name": "Yoke", "code": None, "reason": "unsupported"}],
        )

    def test_invalid_paste_json_has_redacted_useful_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "import_json"):
            load_fixture_import_json("{not json")

    def test_redaction_scrubs_nested_keys_and_pasted_json(self) -> None:
        payload = {
            "net_key": NET_KEY,
            "fixtures": [{"app_key": APP_KEY, "name": "Ace"}],
            "import_json": json.dumps({"net_key": NET_KEY}),
        }

        redacted = redact_sensitive(payload)

        self.assertEqual(redacted["net_key"], REDACTED)
        self.assertEqual(redacted["fixtures"][0]["app_key"], REDACTED)
        self.assertEqual(redacted["import_json"], REDACTED)

    def test_unique_id_prefers_ble_mac(self) -> None:
        self.assertEqual(
            fixture_unique_id(
                {
                    CONF_BLE_MAC: "AA:BB:CC:DD:EE:01",
                    CONF_NODE_ADDRESS: 11,
                }
            ),
                "aa_bb_cc_dd_ee_01",
        )

    def test_unique_id_uses_address_when_it_is_a_mac(self) -> None:
        self.assertEqual(
            fixture_unique_id(
                {
                    CONF_ADDRESS: "AA:BB:CC:DD:EE:01",
                    CONF_NODE_ADDRESS: 11,
                }
            ),
                "aa_bb_cc_dd_ee_01",
        )


class FixtureCapabilityTest(unittest.TestCase):
    def test_bi_color_capability_detection(self) -> None:
        for code, name in (
            ("400O5", "amaran 100x S #1"),
            ("400M5", "amaran 60x S #1"),
            (None, "Amaran 100x"),
            (None, "Amaran 60x S"),
        ):
            profile = detect_fixture_profile(code=code, name=name)
            self.assertEqual(profile.color_modes, (COLOR_MODE_COLOR_TEMP,))
            self.assertFalse(profile.supports_hs)

    def test_rgb_fixture_capability_detection(self) -> None:
        for code, name in (
            ("400U5", "amaran Ace 25c #1"),
            ("400W5", "amaran Pano 60c #1"),
            (None, "Amaran Ace 25c"),
            (None, "Amaran Pano 60c"),
        ):
            profile = detect_fixture_profile(code=code, name=name)
            self.assertEqual(profile.color_modes, (COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS))
            self.assertTrue(profile.supports_hs)

    def test_full_color_models_classify_as_rgb(self) -> None:
        for name in (
            "MT Pro",
            "INFINIMAT 4",
            "INFINIMAT 16",
            "INFINIBAR PB3",
            "INFINIBAR PB6",
            "INFINIBAR PB12",
        ):
            with self.subTest(name=name):
                profile = detect_fixture_profile(name=name)

                self.assertEqual(
                    profile.color_modes, (COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS)
                )

    def test_verge_and_go_stay_cct_only(self) -> None:
        for name in ("amaran Verge", "amaran Verge Max", "amaran Go"):
            with self.subTest(name=name):
                profile = detect_fixture_profile(name=name)

                self.assertEqual(profile.color_modes, (COLOR_MODE_COLOR_TEMP,))

    def test_motorized_accessories_are_unsupported(self) -> None:
        for name in ("Motorized Yoke", "Motorized F14 Fresnel"):
            with self.subTest(name=name):
                profile = detect_fixture_profile(name=name)

                self.assertFalse(profile.supported)
                self.assertEqual(profile.color_modes, ())

    def test_bundled_catalog_loads_and_is_non_empty(self) -> None:
        from custom_components.amaran.product_catalog import product_catalog

        catalog = product_catalog()

        self.assertGreaterEqual(len(catalog), 78)
        self.assertTrue(all(p.name or p.hex_code for p in catalog))

    def test_product_catalog_matches_by_product_id(self) -> None:
        profile = detect_fixture_profile(product_id=91)

        self.assertEqual(profile.model, "amaran Ace 25c")
        self.assertEqual(profile.color_modes, (COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS))

    def test_product_catalog_matches_by_hex_code(self) -> None:
        profile = detect_fixture_profile(code="400W5")

        self.assertEqual(profile.model, "amaran Pano 60c")
        self.assertEqual(profile.color_modes, (COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS))

    def test_product_catalog_fallback_name_detects_rgb_family(self) -> None:
        for name in ("P60c", "F21c", "F22c", "PT4c", "T2c", "MC", "Nova P300c"):
            with self.subTest(name=name):
                profile = detect_fixture_profile(name=name)

                self.assertEqual(
                    profile.color_modes, (COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS)
                )

    def test_product_catalog_fallback_name_detects_cct_family(self) -> None:
        for name in ("100x", "60x S", "P60x"):
            with self.subTest(name=name):
                profile = detect_fixture_profile(name=name)

                self.assertEqual(profile.color_modes, (COLOR_MODE_COLOR_TEMP,))

    def test_product_catalog_classifies_daylight_as_brightness_only(self) -> None:
        profile = detect_fixture_profile(code="400N5")

        self.assertEqual(profile.model, "amaran 100d S")
        self.assertEqual(profile.color_modes, (COLOR_MODE_BRIGHTNESS,))

    def test_unknown_fixture_defaults_to_cct_only(self) -> None:
        profile = detect_fixture_profile(name="Unknown fixture", model="Mystery")

        self.assertEqual(profile.color_modes, (COLOR_MODE_COLOR_TEMP,))
        self.assertFalse(profile.supports_hs)

    def test_legacy_unknown_verge_import_uses_catalog_name(self) -> None:
        imported = load_fixture_import_json(
            json.dumps(
                {
                    "net_key": NET_KEY,
                    "app_key": APP_KEY,
                    "fixtures": [
                        {
                            "name": "amaran Verge Max",
                            "model": "Unknown",
                            "mac_address": "AA:BB:CC:DD:EE:07",
                            "node_address": 15,
                            "capabilities": ["brightness", "color_temp"],
                        }
                    ],
                }
            )
        )
        fixture = imported.fixtures[0]

        self.assertEqual(fixture[CONF_MODEL], "amaran Verge Max")
        self.assertEqual(fixture[CONF_SUPPORTED_COLOR_MODES], [COLOR_MODE_COLOR_TEMP])
        self.assertEqual(
            light_capability_names(fixture),
            ("Brightness", "Color temperature"),
        )

    def test_explicit_brightness_and_color_temp_keeps_color_temp(self) -> None:
        modes = supported_color_modes_for_fixture(
            {
                CONF_MODEL: "Mystery",
                "capabilities": ["brightness", "color_temp"],
            }
        )

        self.assertEqual(modes, (COLOR_MODE_COLOR_TEMP,))

    def test_stale_ace_entry_with_cct_only_still_gets_hs(self) -> None:
        modes = supported_color_modes_for_fixture(
            {
                CONF_NAME: "amaran Ace 25c #1",
                CONF_MODEL: "Ace 25c",
                CONF_SUPPORTED_COLOR_MODES: [COLOR_MODE_COLOR_TEMP],
            }
        )

        self.assertEqual(modes, (COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS))

    def test_known_bicolor_ignores_bad_explicit_hs(self) -> None:
        modes = supported_color_modes_for_fixture(
            {
                CONF_NAME: "amaran 60x S #1",
                CONF_MODEL: "60x S",
                CONF_SUPPORTED_COLOR_MODES: [COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS],
            }
        )

        self.assertEqual(modes, (COLOR_MODE_COLOR_TEMP,))

    def test_battery_capability_detection(self) -> None:
        for name in ("amaran Ace 25c", "amaran PT1c", "amaran PT2c", "amaran PT4c"):
            with self.subTest(name=name):
                self.assertTrue(is_battery_capable_light({CONF_MODEL: name}))

        for name in ("amaran 100x S", "amaran 60x S", "amaran Pano 60c"):
            with self.subTest(name=name):
                self.assertFalse(is_battery_capable_light({CONF_MODEL: name}))

    def test_friendly_capability_names_include_battery_when_supported(self) -> None:
        self.assertEqual(
            light_capability_names(
                {
                    CONF_MODEL: "amaran Ace 25c",
                    CONF_SUPPORTED_COLOR_MODES: [
                        COLOR_MODE_COLOR_TEMP,
                        COLOR_MODE_HS,
                    ],
                    CONF_BATTERY_CAPABLE: True,
                }
            ),
            ("Brightness", "Color temperature", "Color/HSI", "Battery"),
        )


def _write_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            create table mesh (
                uuid text primary key,
                net_key text,
                app_key text,
                fixtures_ordered_list text,
                update_time integer
            )
            """
        )
        conn.execute(
            """
            create table fixtures (
                uuid text primary key,
                mac_address text,
                code text,
                name text,
                node_address integer,
                device_uuid text,
                state integer
            )
            """
        )
        conn.execute(
            """
            insert into mesh values (?, ?, ?, ?, ?)
            """,
            (
                "mesh-1",
                NET_KEY,
                APP_KEY,
                "400O5-F68F27,400W5-517E2B,400M5-12A03E,400U5-51B1BF",
                10,
            ),
        )
        rows = [
            ("f1", "AA:BB:CC:DD:EE:04", "400O5", "amaran 100x S #1", 2, "d1", 1),
            ("f2", "AA:BB:CC:DD:EE:02", "400W5", "amaran Pano 60c #1", 4, "d2", 1),
            ("f3", "AA:BB:CC:DD:EE:03", "400M5", "amaran 60x S #1", 10, "d3", 1),
            ("f4", "AA:BB:CC:DD:EE:01", "400U5", "amaran Ace 25c #1", 11, "d4", 1),
            ("f5", "AA:BB:CC:DD:EE:06", "99999", "Unknown fixture", 12, "d5", 1),
        ]
        conn.executemany("insert into fixtures values (?, ?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
    finally:
        conn.close()


def _write_db_with_product_id(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            create table mesh (
                uuid text primary key,
                net_key text,
                app_key text,
                fixtures_ordered_list text,
                update_time integer
            )
            """
        )
        conn.execute(
            """
            create table fixtures (
                uuid text primary key,
                mac_address text,
                code text,
                name text,
                node_address integer,
                device_uuid text,
                state integer,
                product_id integer
            )
            """
        )
        conn.execute(
            """
            insert into mesh values (?, ?, ?, ?, ?)
            """,
            ("mesh-1", NET_KEY, APP_KEY, "400M5-51B1BF", 10),
        )
        conn.execute(
            "insert into fixtures values (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "f1",
                "AA:BB:CC:DD:EE:01",
                "400M5",
                "Product ID wins",
                11,
                "d1",
                1,
                91,
            ),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    unittest.main()
