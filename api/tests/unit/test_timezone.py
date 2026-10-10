from datetime import UTC, date, datetime

from tti.domain.timezone import today_for


def test_today_in_utc_matches_utc_date():
    now_utc = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    assert today_for("UTC", now_utc) == date(2026, 6, 15)


def test_midnight_boundary_a_timezone_ahead_of_utc_is_already_tomorrow():
    # 23:30 UTC on the 14th is 00:30 on the 15th in a UTC+1 zone.
    now_utc = datetime(2026, 6, 14, 23, 30, tzinfo=UTC)
    assert today_for("Europe/Lisbon", now_utc) in (date(2026, 6, 14), date(2026, 6, 15))
    # Lisbon is UTC+1 in June (BST-equivalent, WEST) — explicitly the
    # later date, not a tautology.
    assert today_for("Europe/Lisbon", now_utc) == date(2026, 6, 15)


def test_midnight_boundary_a_timezone_behind_utc_is_still_yesterday():
    # 03:00 UTC on Jan 1st is 19:00 on Dec 31st in Los Angeles (UTC-8 in
    # January) — a real employee's local "today" can be a full calendar
    # day, and year, behind the server's UTC instant.
    now_utc = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    assert today_for("America/Los_Angeles", now_utc) == date(2025, 12, 31)
