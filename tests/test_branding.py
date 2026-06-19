"""Integration branding tests."""

from __future__ import annotations

import json
from pathlib import Path
import struct
import unittest


ROOT = Path(__file__).parents[1]
INTEGRATION_DIR = Path(__file__).parents[1] / "custom_components" / "amaran"
BRAND_DIR = INTEGRATION_DIR / "brand"


class BrandingTest(unittest.TestCase):
    def test_manifest_domain_and_display_name(self) -> None:
        manifest = json.loads((INTEGRATION_DIR / "manifest.json").read_text())

        self.assertEqual(manifest["domain"], "amaran")
        self.assertEqual(manifest["name"], "amaran")
        self.assertEqual(manifest["version"], "0.4.5")
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["integration_type"], "device")
        self.assertIn(manifest["iot_class"], {"local_push", "local_polling"})

    def test_manifest_does_not_advertise_bluetooth_discovery(self) -> None:
        manifest = json.loads((INTEGRATION_DIR / "manifest.json").read_text())

        self.assertNotIn("bluetooth", manifest)

    def test_hacs_metadata(self) -> None:
        hacs = json.loads((ROOT / "hacs.json").read_text())

        self.assertEqual(hacs["name"], "amaran")
        self.assertIs(hacs["content_in_root"], False)
        self.assertIs(hacs["render_readme"], True)

    def test_required_publish_files_exist(self) -> None:
        required_root = [
            "README.md",
            "LICENSE",
            "CHANGELOG.md",
            "SECURITY.md",
            "hacs.json",
            "pyproject.toml",
        ]
        required_integration = [
            "__init__.py",
            "manifest.json",
            "config_flow.py",
            "light.py",
            "sensor.py",
            "strings.json",
            "translations/en.json",
            "product.json",
        ]

        for path in required_root:
            self.assertTrue((ROOT / path).is_file(), path)
        for path in required_integration:
            self.assertTrue((INTEGRATION_DIR / path).is_file(), path)
        self.assertTrue((INTEGRATION_DIR / "brand").is_dir())
        legacy_domain = "amaran" + "_sidus"
        self.assertFalse((ROOT / "custom_components" / legacy_domain).exists())

    def test_brand_assets_are_png_with_expected_shapes(self) -> None:
        icon = _png_info(BRAND_DIR / "icon.png")
        logo = _png_info(BRAND_DIR / "logo.png")

        self.assertEqual(icon[:2], (512, 512))
        self.assertTrue(icon.has_alpha)
        self.assertGreater(logo.width, logo.height)
        self.assertTrue(logo.has_alpha)


class PngInfo(tuple):
    width: int
    height: int
    color_type: int

    def __new__(cls, width: int, height: int, color_type: int) -> "PngInfo":
        return super().__new__(cls, (width, height, color_type))

    @property
    def width(self) -> int:
        return self[0]

    @property
    def height(self) -> int:
        return self[1]

    @property
    def has_alpha(self) -> bool:
        return self[2] in (4, 6)


def _png_info(path: Path) -> PngInfo:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"{path} is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    color_type = data[25]
    return PngInfo(width, height, color_type)


if __name__ == "__main__":
    unittest.main()
