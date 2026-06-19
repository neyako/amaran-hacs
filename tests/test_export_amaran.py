"""amaran Desktop export script tests."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest

from custom_components.amaran.fixtures import load_fixture_import_json

ROOT = Path(__file__).resolve().parents[1]
EXPORT_SCRIPT = ROOT / "scripts" / "export_amaran.py"
NET_KEY = "00112233445566778899aabbccddeeff"
APP_KEY = "ffeeddccbbaa99887766554433221100"


def _load_export_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_amaran", EXPORT_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXPORT = _load_export_module()


class ExportAmaranTest(unittest.TestCase):
    def test_catalog_resolves_verge_max_by_id_code_and_name(self) -> None:
        for lookup in (
            {"product_id": 105},
            {"code": "400Z5"},
            {"name": "amaran Verge Max"},
        ):
            with self.subTest(lookup=lookup):
                product = EXPORT.lookup_catalog_product(**lookup)
                self.assertIsNotNone(product)
                self.assertEqual(product["name"], "amaran Verge Max")

    def test_windows_path_detection_checks_appdata_and_userprofile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            appdata = root / "AppData" / "Roaming"
            localappdata = root / "AppData" / "Local"
            userprofile = root / "User"
            env = {
                "APPDATA": str(appdata),
                "LOCALAPPDATA": str(localappdata),
                "USERPROFILE": str(userprofile),
            }

            older = appdata / "amaran Desktop" / "111_secure_id" / "amaran.db"
            newest = (
                userprofile
                / "AppData"
                / "Local"
                / "amaran Desktop"
                / "222_secure_id"
                / "amaran.db"
            )
            _touch_db(older, mtime=100)
            _touch_db(newest, mtime=200)

            patterns = [
                pattern
                for pattern in EXPORT.desktop_db_globs(env)
                if str(root) in pattern
            ]

            self.assertIn(
                str(appdata / "amaran Desktop" / "*_secure_id" / "amaran.db"),
                patterns,
            )
            self.assertIn(
                str(localappdata / "amaran Desktop" / "*_secure_id" / "amaran.db"),
                patterns,
            )
            self.assertIn(
                str(
                    userprofile
                    / "AppData"
                    / "Roaming"
                    / "amaran Desktop"
                    / "*_secure_id"
                    / "amaran.db"
                ),
                patterns,
            )
            self.assertIn(
                str(
                    userprofile
                    / "AppData"
                    / "Local"
                    / "amaran Desktop"
                    / "*_secure_id"
                    / "amaran.db"
                ),
                patterns,
            )
            self.assertEqual(EXPORT.find_desktop_db(patterns), newest)

    def test_exported_json_imports_through_ha_fixture_loader(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "amaran.db"
            _create_amaran_db(db_path)

            payload = EXPORT.export_payload(db_path)
            imported = load_fixture_import_json(json.dumps(payload))

            self.assertEqual(
                [fixture["model"] for fixture in payload["fixtures"]],
                [
                    "amaran 100x S",
                    "amaran Pano 60c",
                    "amaran 60x S",
                    "amaran Ace 25c",
                    "amaran Verge Max",
                ],
            )
            self.assertEqual(len(imported.fixtures), 5)
            self.assertEqual(
                [fixture["name"] for fixture in imported.fixtures],
                ["Key 100x S", "Pano", "60x S", "Ace", "Desk light"],
            )
            self.assertEqual(
                [fixture["node_address"] for fixture in imported.fixtures],
                [0x000B, 0x000C, 0x000D, 0x000E, 0x000F],
            )
            self.assertNotIn("hs", imported.fixtures[0]["supported_color_modes"])
            self.assertIn("hs", imported.fixtures[1]["supported_color_modes"])
            self.assertNotIn("hs", imported.fixtures[2]["supported_color_modes"])
            self.assertIn("hs", imported.fixtures[3]["supported_color_modes"])
            self.assertEqual(
                imported.fixtures[4]["supported_color_modes"], ["color_temp"]
            )
            self.assertEqual(
                payload["fixtures"][4]["capabilities"],
                ["brightness", "color_temp"],
            )

    def test_stdout_flag_writes_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "amaran.db"
            _create_amaran_db(db_path)

            result = subprocess.run(
                [
                    sys.executable,
                    str(EXPORT_SCRIPT),
                    "--db",
                    str(db_path),
                    "--stdout",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(len(payload["fixtures"]), 5)
            self.assertEqual(result.stderr, "")

    def test_output_file_prints_friendly_message_without_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "amaran.db"
            _create_amaran_db(db_path)

            result = subprocess.run(
                [
                    sys.executable,
                    str(EXPORT_SCRIPT),
                    "--db",
                    str(db_path),
                    "--output",
                    "amaran-export.json",
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.stdout, "Export written to amaran-export.json\n")
            self.assertEqual(result.stderr, "")
            self.assertNotIn(NET_KEY, result.stdout + result.stderr)
            self.assertNotIn(APP_KEY, result.stdout + result.stderr)
            self.assertEqual(
                len(json.loads((root / "amaran-export.json").read_text())["fixtures"]),
                5,
            )


def _touch_db(path: Path, *, mtime: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, (mtime, mtime))


def _create_amaran_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            create table mesh (
                uuid text,
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
                uuid text,
                mac_address text,
                code text,
                name text,
                node_address integer,
                product_id integer
            )
            """
        )
        conn.execute(
            """
            insert into mesh
                (uuid, net_key, app_key, fixtures_ordered_list, update_time)
            values (?, ?, ?, ?, ?)
            """,
            ("mesh-1", NET_KEY, APP_KEY, "", 1),
        )
        conn.executemany(
            """
            insert into fixtures
                (uuid, mac_address, code, name, node_address, product_id)
            values (?, ?, ?, ?, ?, ?)
            """,
            [
                ("100x", "AA:BB:CC:DD:EE:01", "400O5", "Key 100x S", 0x000B, None),
                ("pano", "AA:BB:CC:DD:EE:02", "400W5", "Pano", 0x000C, None),
                ("60x", "AA:BB:CC:DD:EE:03", "400M5", "60x S", 0x000D, None),
                ("ace", "AA:BB:CC:DD:EE:04", "400U5", "Ace", 0x000E, None),
                ("verge", "AA:BB:CC:DD:EE:05", "400Z5", "Desk light", 0x000F, 105),
            ],
        )


if __name__ == "__main__":
    unittest.main()
