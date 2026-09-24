from tti.entries.service import _failure_for
from tti.outbox.errors import OdooWriteRejected
from tti.outbox.service import PERIOD_LOCKED_PREFIX
from tti.periods.errors import PeriodLocked


def test_a_lock_that_landed_between_save_and_write_is_a_409_not_an_odoo_rejection():
    exc = _failure_for(PERIOD_LOCKED_PREFIX + "2026-08-31 is locked for employee 1")
    assert isinstance(exc, PeriodLocked) and exc.code == "period_locked"
    assert str(exc) == "2026-08-31 is locked for employee 1"


def test_anything_else_stays_an_odoo_rejection():
    assert isinstance(_failure_for("odoo said no"), OdooWriteRejected)
    assert isinstance(_failure_for(None), OdooWriteRejected)
