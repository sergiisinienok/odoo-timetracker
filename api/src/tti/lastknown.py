"""Last-known-value cache — docs/decisions/0010, gap 2.

Two ages, two questions. A value is *fresh* for `ttl` seconds: use it without
asking Odoo again. It stays *usable when Odoo is unreachable* for `ceiling`
seconds after it was read: better a day-old answer than refusing an
employee's input during an outage. Nothing is ever served stale while Odoo can
answer, and a cold cache (never read, or older than the ceiling) is a miss —
the caller must then refuse rather than guess.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable

DEFAULT_CEILING_SECONDS = 24 * 60 * 60


class LastKnownCache[V]:
    def __init__(
        self, *, ttl: float, ceiling: float = DEFAULT_CEILING_SECONDS, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl = ttl
        self._ceiling = ceiling
        self._clock = clock
        self._entries: dict[Hashable, tuple[V, float, float]] = {}  # value, read_at, fresh_until

    def put(self, key: Hashable, value: V) -> None:
        now = self._clock()
        self._entries[key] = (value, now, now + self._ttl)

    def fresh(self, key: Hashable) -> V | None:
        entry = self._entries.get(key)
        if entry is not None and self._clock() < entry[2]:
            return entry[0]
        return None

    def last_known(self, key: Hashable) -> V | None:
        """Only for use when Odoo could not be asked."""
        entry = self._entries.get(key)
        if entry is not None and self._clock() - entry[1] < self._ceiling:
            return entry[0]
        return None

    def invalidate(self, key: Hashable) -> None:
        """No longer fresh — the next read must go to Odoo. The value stays
        available as a last resort if Odoo then can't be reached."""
        entry = self._entries.get(key)
        if entry is not None:
            self._entries[key] = (entry[0], entry[1], 0.0)
