from datetime import date

from tti.domain.period import PeriodState, resolve_period_state


def test_date_exactly_on_the_validated_through_date_is_locked():
    assert resolve_period_state(date(2026, 8, 31), date(2026, 8, 31), None) == PeriodState.LOCKED


def test_date_the_day_after_validated_through_is_open():
    assert resolve_period_state(date(2026, 9, 1), date(2026, 8, 31), None) == PeriodState.OPEN


def test_date_well_before_validated_through_is_locked():
    assert resolve_period_state(date(2026, 3, 1), date(2026, 8, 31), None) == PeriodState.LOCKED


def test_date_in_an_earlier_year_than_validated_through_is_locked():
    # Not a string-prefix trick — resolve_period_state compares real date
    # objects, so a year boundary can't accidentally make an earlier date
    # look "later" the way lexical comparison on badly-formatted strings
    # could.
    assert resolve_period_state(date(2025, 12, 31), date(2026, 8, 31), None) == PeriodState.LOCKED


def test_date_in_a_later_year_than_validated_through_is_open():
    assert resolve_period_state(date(2027, 1, 1), date(2026, 8, 31), None) == PeriodState.OPEN


def test_falls_back_to_company_validated_through_when_employee_has_none():
    assert resolve_period_state(date(2026, 8, 31), None, date(2026, 8, 31)) == PeriodState.LOCKED
    assert resolve_period_state(date(2026, 9, 1), None, date(2026, 8, 31)) == PeriodState.OPEN


def test_employee_signal_takes_priority_over_company_signal():
    # Employee validated further than the company-wide date — the more
    # specific (employee) signal wins.
    assert (
        resolve_period_state(date(2026, 9, 15), date(2026, 9, 30), date(2026, 6, 30)) == PeriodState.LOCKED
    )


def test_no_signal_at_all_resolves_open():
    # docs/decisions/0003: this instance has no company-level
    # validated-through field, so an employee nobody has validated yet
    # has no locking signal at all — stays editable rather than locked by
    # default. Deliberate, not an oversight.
    assert resolve_period_state(date(2020, 1, 1), None, None) == PeriodState.OPEN
