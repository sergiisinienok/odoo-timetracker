from decimal import Decimal

import pytest

from tti.domain.daily_cap import validate_daily_cap
from tti.domain.errors import DailyCapExceeded


def test_exactly_at_the_cap_is_accepted():
    validate_daily_cap(Decimal("7.75"), Decimal("0.25"), Decimal("8.00"))  # no exception


def test_one_increment_over_the_cap_is_rejected():
    with pytest.raises(DailyCapExceeded):
        validate_daily_cap(Decimal("7.75"), Decimal("0.50"), Decimal("8.00"))


def test_well_under_the_cap_is_accepted():
    validate_daily_cap(Decimal("2.00"), Decimal("1.00"), Decimal("8.00"))  # no exception


def test_existing_alone_already_at_cap_plus_any_new_hours_is_rejected():
    with pytest.raises(DailyCapExceeded):
        validate_daily_cap(Decimal("8.00"), Decimal("0.25"), Decimal("8.00"))


def test_zero_new_hours_at_exactly_the_cap_is_accepted():
    validate_daily_cap(Decimal("8.00"), Decimal(0), Decimal("8.00"))  # no exception
