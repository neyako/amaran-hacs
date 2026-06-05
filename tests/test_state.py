"""Optimistic fixture state planning tests."""

from __future__ import annotations

import unittest

from custom_components.amaran.const import COLOR_MODE_COLOR_TEMP, COLOR_MODE_HS
from custom_components.amaran.state import (
    COMMAND_BRIGHTNESS,
    COMMAND_CCT,
    COMMAND_HSI,
    FixtureCachedState,
    plan_turn_on,
    turn_off_state,
)


class FixtureStatePlanTest(unittest.TestCase):
    def test_brightness_in_hs_mode_preserves_hue_saturation(self) -> None:
        state = FixtureCachedState(
            power=True,
            brightness=128,
            hs_color=(45.0, 60.0),
            active_color_mode=COLOR_MODE_HS,
        )

        plan = plan_turn_on(state, supports_hs=True, brightness=204)

        self.assertEqual(plan.command, COMMAND_HSI)
        self.assertEqual(plan.state.brightness, 204)
        self.assertEqual(plan.state.hs_color, (45.0, 60.0))
        self.assertEqual(plan.state.active_color_mode, COLOR_MODE_HS)

    def test_brightness_in_cct_mode_preserves_cct(self) -> None:
        state = FixtureCachedState(
            power=True,
            brightness=128,
            color_temp_kelvin=3200,
            active_color_mode=COLOR_MODE_COLOR_TEMP,
        )

        plan = plan_turn_on(state, supports_hs=True, brightness=204)

        self.assertEqual(plan.command, COMMAND_BRIGHTNESS)
        self.assertEqual(plan.state.brightness, 204)
        self.assertEqual(plan.state.color_temp_kelvin, 3200)
        self.assertEqual(plan.state.active_color_mode, COLOR_MODE_COLOR_TEMP)

    def test_cct_change_does_not_reset_brightness(self) -> None:
        state = FixtureCachedState(
            power=True,
            brightness=153,
            color_temp_kelvin=3200,
            hs_color=(45.0, 60.0),
            active_color_mode=COLOR_MODE_HS,
        )

        plan = plan_turn_on(state, supports_hs=True, kelvin=5600)

        self.assertEqual(plan.command, COMMAND_CCT)
        self.assertEqual(plan.state.brightness, 153)
        self.assertEqual(plan.state.color_temp_kelvin, 5600)
        self.assertEqual(plan.state.hs_color, (45.0, 60.0))
        self.assertEqual(plan.state.active_color_mode, COLOR_MODE_COLOR_TEMP)

    def test_hs_change_does_not_reset_brightness(self) -> None:
        state = FixtureCachedState(
            power=True,
            brightness=153,
            color_temp_kelvin=3200,
            active_color_mode=COLOR_MODE_COLOR_TEMP,
        )

        plan = plan_turn_on(state, supports_hs=True, hs_color=(240, 75))

        self.assertEqual(plan.command, COMMAND_HSI)
        self.assertEqual(plan.state.brightness, 153)
        self.assertEqual(plan.state.color_temp_kelvin, 3200)
        self.assertEqual(plan.state.hs_color, (240.0, 75.0))
        self.assertEqual(plan.state.active_color_mode, COLOR_MODE_HS)

    def test_turn_on_restores_last_hs_mode(self) -> None:
        state = FixtureCachedState(
            power=False,
            brightness=200,
            color_temp_kelvin=5600,
            hs_color=(120.0, 80.0),
            active_color_mode=COLOR_MODE_HS,
        )

        plan = plan_turn_on(state, supports_hs=True)

        self.assertEqual(plan.command, COMMAND_HSI)
        self.assertTrue(plan.power_on)
        self.assertEqual(plan.state.brightness, 200)
        self.assertEqual(plan.state.hs_color, (120.0, 80.0))
        self.assertEqual(plan.state.active_color_mode, COLOR_MODE_HS)

    def test_turn_off_preserves_cached_values(self) -> None:
        state = FixtureCachedState(
            power=True,
            brightness=200,
            color_temp_kelvin=5600,
            hs_color=(120.0, 80.0),
            active_color_mode=COLOR_MODE_HS,
        )

        next_state = turn_off_state(state)

        self.assertFalse(next_state.power)
        self.assertEqual(next_state.brightness, 200)
        self.assertEqual(next_state.color_temp_kelvin, 5600)
        self.assertEqual(next_state.hs_color, (120.0, 80.0))
        self.assertEqual(next_state.active_color_mode, COLOR_MODE_HS)


if __name__ == "__main__":
    unittest.main()
