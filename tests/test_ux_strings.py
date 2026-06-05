"""User-facing wording regressions."""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).parents[1]


class UserFacingStringTest(unittest.TestCase):
    def test_config_flow_strings_do_not_say_fixture(self) -> None:
        translations = json.loads(
            (ROOT / "custom_components/amaran/translations/en.json").read_text(
                encoding="utf-8"
            )
        )

        values = "\n".join(_string_values(translations)).lower()

        self.assertNotIn("fixture", values)
        self.assertNotIn("proxy", values)
        self.assertNotIn("transport", values)
        self.assertIn("export your amaran lights from the desktop app", values)
        self.assertIn("raw.githubusercontent.com/neyako/amaran-hacs", values)
        self.assertIn("do not share the exported json publicly", values)

    def test_readme_prose_does_not_say_fixture(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        prose = _strip_code_spans_and_blocks(readme).lower()

        self.assertNotIn("fixture", prose)


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for child in value.values():
            values.extend(_string_values(child))
        return values
    if isinstance(value, list):
        values = []
        for child in value:
            values.extend(_string_values(child))
        return values
    return []


def _strip_code_spans_and_blocks(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`]*`", "", text)


if __name__ == "__main__":
    unittest.main()
