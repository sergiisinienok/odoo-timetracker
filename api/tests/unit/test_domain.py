import pytest

from tti.domain.increments import is_valid_increment
from tti.domain.validity import is_date_within_validity


@pytest.mark.parametrize(
    "hours,expected",
    [
        (3.25, True),
        (0.25, True),
        (8.0, True),
        (3.3, False),
        (0, False),
        (-0.25, False),
        (0.1, False),
    ],
)
def test_is_valid_increment(hours, expected):
    assert is_valid_increment(hours) is expected


def test_open_ended_assignment_accepts_any_date():
    assert is_date_within_validity("2026-01-01", None, None) is True


def test_date_before_start_is_rejected():
    assert is_date_within_validity("2026-01-01", "2026-02-01", None) is False


def test_date_after_end_is_rejected():
    assert is_date_within_validity("2026-03-01", None, "2026-02-01") is False


def test_date_within_window_is_accepted():
    assert is_date_within_validity("2026-01-15", "2026-01-01", "2026-01-31") is True
