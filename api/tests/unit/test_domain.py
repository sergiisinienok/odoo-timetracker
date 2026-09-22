from datetime import date
from decimal import Decimal

import pytest

from tti.domain.errors import AssignmentNotValidOnDate, InvalidIncrement
from tti.domain.increments import validate_increment
from tti.domain.validity import validate_within_assignment


@pytest.mark.parametrize(
    "hours",
    [Decimal("3.25"), Decimal("0.25"), Decimal("8.0")],
)
def test_valid_increment_does_not_raise(hours):
    validate_increment(hours)  # no exception


@pytest.mark.parametrize(
    "hours",
    [Decimal("3.3"), Decimal("0"), Decimal("-0.25"), Decimal("0.1")],
)
def test_invalid_increment_raises(hours):
    with pytest.raises(InvalidIncrement):
        validate_increment(hours)


def test_open_ended_assignment_accepts_any_date():
    validate_within_assignment(date(2026, 1, 1), None, None)  # no exception


def test_date_before_start_is_rejected():
    with pytest.raises(AssignmentNotValidOnDate):
        validate_within_assignment(date(2026, 1, 1), date(2026, 2, 1), None)


def test_date_after_end_is_rejected():
    with pytest.raises(AssignmentNotValidOnDate):
        validate_within_assignment(date(2026, 3, 1), None, date(2026, 2, 1))


def test_date_within_window_is_accepted():
    validate_within_assignment(date(2026, 1, 15), date(2026, 1, 1), date(2026, 1, 31))  # no exception


def test_date_exactly_on_start_is_accepted():
    validate_within_assignment(date(2026, 1, 1), date(2026, 1, 1), None)  # no exception


def test_date_exactly_on_end_is_accepted():
    validate_within_assignment(date(2026, 1, 31), None, date(2026, 1, 31))  # no exception
