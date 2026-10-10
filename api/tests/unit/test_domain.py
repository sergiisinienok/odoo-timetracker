from decimal import Decimal

import pytest

from tti.domain.errors import InvalidIncrement
from tti.domain.increments import validate_increment


@pytest.mark.parametrize(
    "hours",
    [Decimal("3.25"), Decimal("0.25"), Decimal("8.0")],
)
def test_valid_increment_does_not_raise(hours):
    validate_increment(hours)  # no exception


@pytest.mark.parametrize(
    "hours",
    [Decimal("3.3"), Decimal(0), Decimal("-0.25"), Decimal("0.1")],
)
def test_invalid_increment_raises(hours):
    with pytest.raises(InvalidIncrement):
        validate_increment(hours)
