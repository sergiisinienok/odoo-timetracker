"""Pure rule: what date is "today" for an employee, given the current UTC
instant — the employee's own timezone defines it (step 1.3's reason for
putting timezone in the session), not the server's.

`now_utc` is a parameter rather than read from the system clock so this
stays a pure function — same inputs, same output, no wall-clock
dependency to mock in tests.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


def today_for(tz: str, now_utc: datetime) -> date:
    return now_utc.astimezone(ZoneInfo(tz)).date()
