"""Gap 2 (docs/decisions/0010): last-known values during an Odoo outage.
Network disabled, fake clock and stub Odoo — these are the rules, the
live-Odoo outage test is in tests/odoo/test_phase2_outage.py."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from tti.catalog.service import CatalogProject, CatalogService, Snapshot
from tti.entries.service import EntryService
from tti.lastknown import LastKnownCache
from tti.odoo.errors import OdooUnavailable, OdooUncertain
from tti.periods.service import PeriodService


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_fresh_then_stale_then_beyond_the_ceiling():
    clock = Clock()
    cache = LastKnownCache(ttl=60, ceiling=3600, clock=clock)
    cache.put("k", "v")
    assert cache.fresh("k") == "v" and cache.last_known("k") == "v"
    clock.now += 61
    assert cache.fresh("k") is None and cache.last_known("k") == "v"
    clock.now += 3600
    assert cache.last_known("k") is None


def test_cold_cache_is_a_miss():
    cache = LastKnownCache(ttl=60)
    assert cache.fresh("k") is None and cache.last_known("k") is None


def test_invalidate_forces_a_live_read_but_keeps_the_last_resort():
    cache = LastKnownCache(ttl=60)
    cache.put("k", "v")
    cache.invalidate("k")
    assert cache.fresh("k") is None and cache.last_known("k") == "v"


def test_a_cached_falsy_value_is_still_a_hit():
    cache = LastKnownCache(ttl=60)
    cache.put("k", [])
    assert cache.fresh("k") == [] and cache.last_known("k") == []


# --- periods --------------------------------------------------------------------------


class ScriptedOdoo:
    """Answers with the queued results in order; an Exception in the queue is raised."""

    def __init__(self, *results):
        self.results = list(results)

    async def execute_kw(self, *args, **kwargs):
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _periods(*results):
    profile = MagicMock()
    profile.employee_validated_through = "last_validated_timesheet_date"
    return PeriodService(ScriptedOdoo(*results), profile)


async def test_period_state_falls_back_to_last_known_when_odoo_is_down():
    svc = _periods([{"last_validated_timesheet_date": "2026-08-31"}], OdooUnavailable("down"))
    await svc.guard(1, date(2026, 9, 5))  # read live, cached
    svc.invalidate(1)  # e.g. the TTL ran out
    await svc.guard(1, date(2026, 9, 6))  # Odoo down -> last-known "open after Aug 31" is used
    from tti.periods.errors import PeriodLocked

    svc2 = _periods([{"last_validated_timesheet_date": "2026-08-31"}], OdooUncertain("lost"))
    await svc2.guard(1, date(2026, 9, 5))
    svc2.invalidate(1)
    with pytest.raises(PeriodLocked):  # the last-known lock still locks
        await svc2.guard(1, date(2026, 8, 31))


async def test_period_state_with_no_last_known_still_raises():
    svc = _periods(OdooUnavailable("down"))
    with pytest.raises(OdooUnavailable):
        await svc.guard(1, date(2026, 9, 5))


async def test_the_write_time_check_never_uses_last_known():
    svc = _periods([{"last_validated_timesheet_date": False}], OdooUnavailable("down"))
    await svc.guard(1, date(2026, 9, 5))
    svc.invalidate(1)
    with pytest.raises(OdooUnavailable):
        await svc.guard(1, date(2026, 9, 5), allow_last_known=False)


async def test_a_cached_no_lock_value_counts_as_known():
    """None (nothing validated) is a real answer, not a cache miss."""
    svc = _periods([{"last_validated_timesheet_date": False}], OdooUnavailable("down"))
    await svc.guard(1, date(2026, 9, 5))
    svc.invalidate(1)
    await svc.guard(1, date(2026, 9, 5))  # served from last-known, no raise


# --- catalog --------------------------------------------------------------------------


def _snapshot():
    return Snapshot(
        projects=[CatalogProject(id=1, label="Internal", tasks=(), is_default=True, last_used_task_id=None)],
        billing={},
    )


async def test_catalog_falls_back_to_last_known_when_odoo_is_down(monkeypatch):
    svc = CatalogService(MagicMock(), MagicMock())
    calls = iter([_snapshot(), OdooUnavailable("down")])

    async def build(employee_id):
        r = next(calls)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(svc, "_build", build)
    first = await svc.snapshot(1)
    svc._cache.invalidate(1)
    assert await svc.snapshot(1) == first


async def test_a_fresh_snapshot_still_falls_back_to_last_known_when_odoo_is_down(monkeypatch):
    """A save asks for fresh data (is the task open *now*) but must still work
    through an outage, from what was last seen."""
    svc = CatalogService(MagicMock(), MagicMock())
    calls = iter([_snapshot(), OdooUnavailable("down")])

    async def build(employee_id):
        r = next(calls)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(svc, "_build", build)
    first = await svc.snapshot(1)
    assert await svc.snapshot(1, fresh=True) == first


async def test_catalog_with_no_last_known_still_raises(monkeypatch):
    svc = CatalogService(MagicMock(), MagicMock())

    async def build(employee_id):
        raise OdooUnavailable("down")

    monkeypatch.setattr(svc, "_build", build)
    with pytest.raises(OdooUnavailable):
        await svc.snapshot(1)


# --- daily hours ----------------------------------------------------------------------


def _entries(*odoo_results):
    outbox = MagicMock()
    outbox.pending_hours_for = AsyncMock(return_value=Decimal(0))
    return EntryService(ScriptedOdoo(*odoo_results), MagicMock(), MagicMock(), MagicMock(), outbox, Decimal(10))


DAY = date(2026, 9, 24)


async def test_daily_hours_fall_back_to_the_day_as_last_seen():
    svc = _entries(
        [{"id": 7, "unit_amount": 2.5}, {"id": 8, "unit_amount": 1.0}], OdooUnavailable("down"), OdooUnavailable("down")
    )
    assert await svc._existing_hours(1, DAY) == Decimal("3.5")  # live
    assert await svc._existing_hours(1, DAY) == Decimal("3.5")  # outage: last-known
    assert await svc._existing_hours(1, DAY, exclude_odoo_line_id=7) == Decimal("1.0")  # an edit excludes its own line


async def test_daily_hours_with_no_last_known_view_refuse():
    svc = _entries(OdooUnavailable("down"))
    with pytest.raises(OdooUnavailable):
        await svc._existing_hours(1, DAY)


async def test_our_own_synced_writes_keep_the_last_known_day_in_step():
    svc = _entries([{"id": 7, "unit_amount": 2.0}], OdooUnavailable("down"), OdooUnavailable("down"))
    await svc._existing_hours(1, DAY)
    svc._remember_line(1, DAY, 9, Decimal("1.5"))  # we just wrote line 9
    assert await svc._existing_hours(1, DAY) == Decimal("3.5")
    svc._forget_line(1, DAY, 7)  # and deleted line 7
    assert await svc._existing_hours(1, DAY) == Decimal("1.5")


async def test_a_day_never_seen_stays_unknown_rather_than_guessed():
    svc = _entries(OdooUnavailable("down"))
    svc._remember_line(1, DAY, 9, Decimal("1.5"))  # nothing known about the day -> nothing invented
    with pytest.raises(OdooUnavailable):
        await svc._existing_hours(1, DAY)


async def test_pending_rows_still_count_during_the_outage():
    svc = _entries([{"id": 7, "unit_amount": 2.0}], OdooUnavailable("down"))
    svc._outbox.pending_hours_for = AsyncMock(side_effect=[Decimal(0), Decimal("4.0")])
    await svc._existing_hours(1, DAY)
    assert await svc._existing_hours(1, DAY) == Decimal("6.0")  # last-known 2.0 + 4.0 queued
