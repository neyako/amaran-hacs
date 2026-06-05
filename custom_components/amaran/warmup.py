"""Warm-up retry helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WarmupRetryPolicy:
    """Small exponential backoff state for background warm-up attempts."""

    initial_delay: float = 1.0
    max_delay: float = 300.0
    factor: float = 2.0
    _next_delay: float | None = None

    def reset(self) -> None:
        """Reset backoff after a successful warm-up or fresh advertisement."""

        self._next_delay = None

    def next_delay(self) -> float:
        """Return current delay and advance to the next backoff interval."""

        delay = self.initial_delay if self._next_delay is None else self._next_delay
        self._next_delay = min(delay * self.factor, self.max_delay)
        return delay
