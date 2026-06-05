"""Warm-up retry tests."""

from __future__ import annotations

import unittest

from custom_components.amaran.warmup import WarmupRetryPolicy


class WarmupRetryPolicyTest(unittest.TestCase):
    def test_retry_backoff_doubles_and_caps(self) -> None:
        policy = WarmupRetryPolicy(initial_delay=1.0, max_delay=4.0)

        self.assertEqual(policy.next_delay(), 1.0)
        self.assertEqual(policy.next_delay(), 2.0)
        self.assertEqual(policy.next_delay(), 4.0)
        self.assertEqual(policy.next_delay(), 4.0)

    def test_retry_backoff_resets_after_success_or_advertisement(self) -> None:
        policy = WarmupRetryPolicy(initial_delay=1.0, max_delay=4.0)

        policy.next_delay()
        policy.next_delay()
        policy.reset()

        self.assertEqual(policy.next_delay(), 1.0)


if __name__ == "__main__":
    unittest.main()
