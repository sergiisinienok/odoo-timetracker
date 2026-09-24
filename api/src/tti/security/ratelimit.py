"""In-memory sliding-window rate limiter — step 2.8.

Per-process state is deliberate: the api is one container, and the limit is
abuse protection, not a quota. If the api is ever scaled out, each replica
enforces its own window, which only loosens the limit by the replica count.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Hashable

_SWEEP_EVERY = 1024  # checks between sweeps of idle keys


class RateLimiter:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[Hashable, deque[float]] = {}
        self._checks = 0

    def check(self, key: Hashable, *, limit: int, window_seconds: float) -> float | None:
        """Records a hit. Returns None if allowed, else seconds until a slot frees."""
        now = self._clock()
        self._checks += 1
        if self._checks % _SWEEP_EVERY == 0:
            self._sweep(now, window_seconds)

        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return max(hits[0] + window_seconds - now, 0.001)
        hits.append(now)
        return None

    def _sweep(self, now: float, window_seconds: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or h[-1] <= now - window_seconds]:
            del self._hits[key]
