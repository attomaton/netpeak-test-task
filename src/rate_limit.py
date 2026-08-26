"""Thread-safe sliding-window limiter for provider quotas."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class QuotaAwareRateLimiter:
    """Allow at most N requests in a rolling time window.

    A value of zero disables limiting. The limiter is synchronous because the
    Gemini SDK is synchronous and is called from worker threads.
    """

    def __init__(
        self,
        requests_per_window: int = 15,
        window_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if requests_per_window < 0:
            raise ValueError("requests_per_window cannot be negative")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self.sleep = sleep
        self.clock = clock
        self._timestamps: deque[float] = deque()
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until the next provider request is allowed."""

        if self.requests_per_window == 0:
            return
        while True:
            with self._lock:
                now = self.clock()
                self._purge(now)
                if now < self._blocked_until:
                    delay = self._blocked_until - now
                elif len(self._timestamps) < self.requests_per_window:
                    self._timestamps.append(now)
                    return
                else:
                    delay = self.window_seconds - (now - self._timestamps[0])
            self.sleep(max(delay, 0.001))

    def cooldown(self, seconds: float) -> None:
        """Honor a provider Retry-After hint after a quota response."""

        if seconds <= 0:
            return
        with self._lock:
            self._blocked_until = max(self._blocked_until, self.clock() + seconds)

    def _purge(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()

