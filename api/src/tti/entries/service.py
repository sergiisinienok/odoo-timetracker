"""Entry creation, editing, deletion, and listing — steps 1.5 and 2.3/2.4.

Every mutation goes through the outbox (step 2.3): validate, then hand
off to OutboxService, which enqueues as pending and attempts the Odoo
write inline. A synced result gets an honest read-back from Odoo — "the
app never claims a write succeeded on the strength of its own optimism"
(step 1.5) — a pending result is reported from what we know ourselves,
honestly marked not-yet-synced.

Guards, in the order step 2.4 specifies — "employee owns the line,
period is open, assignment is held, date is within assignment validity,
increment is valid, daily cap holds including pending rows" — applied
per operation: create has no existing line to own, so that check is
moot; delete doesn't propose new hours/date/assignment, so validity/
increment/cap don't apply to it.

`name` defaults to a single space when the note is empty — the plan
flagged "Odoo dislikes empty descriptions" as *(verify)*; live-checked
in step 1.5 and an empty string actually works fine on this instance,
but the space default costs nothing and matches what the plan asks for.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal

from tti.assignments.service import AssignmentService
from tti.config import OdooProfile
from tti.domain.daily_cap import validate_daily_cap
from tti.domain.increments import validate_increment
from tti.domain.validity import validate_within_assignment
from tti.entries.errors import AssignmentNotHeld, EntryNotOwned
from tti.odoo.client import OdooClient
from tti.outbox.errors import OdooWriteRejected
from tti.outbox.models import OutboxOp, OutboxRow, OutboxState
from tti.outbox.service import PERIOD_LOCKED_PREFIX, OutboxService
from tti.periods.errors import PeriodLocked
from tti.periods.service import PeriodService


def _failure_for(last_error: str | None) -> Exception:
    """A failed inline attempt is either Odoo refusing the write, or the month
    having locked between the save-time check and the write (409, like any
    other locked-period refusal)."""
    if last_error and last_error.startswith(PERIOD_LOCKED_PREFIX):
        return PeriodLocked(last_error.removeprefix(PERIOD_LOCKED_PREFIX))
    return OdooWriteRejected(last_error or "Odoo rejected the write")


@dataclass(frozen=True)
class CreatedEntry:
    id: int | None  # None until synced — nothing exists in Odoo yet
    outbox_id: str | None
    assignment_id: str
    date: str
    hours: float
    note: str
    project_id: int
    so_line_id: int | None
    sync_state: str  # "synced" | "pending" | "failed"


class EntryService:
    def __init__(
        self,
        odoo: OdooClient,
        profile: OdooProfile,
        assignments: AssignmentService,
        periods: PeriodService,
        outbox: OutboxService,
        internal_project_id: int,
        daily_hour_cap: Decimal,
    ) -> None:
        self._odoo = odoo
        self._profile = profile
        self._assignments = assignments
        self._periods = periods
        self._outbox = outbox
        self._internal_project_id = internal_project_id
        self._daily_hour_cap = daily_hour_cap

    async def create_entry(
        self, *, employee_id: int, assignment_id: str, date: str, hours: float, note: str
    ) -> CreatedEntry:
        # Convert at the boundary: domain rules work in Decimal/date, the
        # rest of this service and the API layer stay in the JSON-native
        # str/float shapes. str(hours) first, never Decimal(hours) direct
        # — see domain/increments.py's own note on why.
        hours_decimal = Decimal(str(hours))
        validate_increment(hours_decimal)

        assignment = await self._find_assignment(employee_id, assignment_id)

        entry_date = date_type.fromisoformat(date)
        start = date_type.fromisoformat(assignment.start_date) if assignment.start_date else None
        end = date_type.fromisoformat(assignment.end_date) if assignment.end_date else None
        validate_within_assignment(entry_date, start, end)

        await self._periods.guard(employee_id, entry_date)

        existing_hours = await self._existing_hours(employee_id, entry_date)
        validate_daily_cap(existing_hours, hours_decimal, self._daily_hour_cap)

        # Paid gets the real sale order line; unpaid and internal both
        # write so_line=False explicitly — the unpaid_recipe confirmed in
        # Phase 0 (odoo_profile.json: "create() with so_line=False passed
        # explicitly").
        so_line_id = assignment.so_line_id if assignment.kind == "paid" else None

        result = await self._outbox.enqueue_create(
            employee_id=employee_id,
            entry_date=entry_date,
            hours=hours_decimal,
            assignment_id=assignment_id,
            project_id=assignment.project_id,
            so_line_id=so_line_id,
            note=note,
        )

        if result.state is OutboxState.FAILED:
            raise _failure_for(result.last_error)

        if result.state is OutboxState.SYNCED:
            assert result.odoo_line_id is not None
            return await self._read_back(result.odoo_line_id, outbox_id=str(result.outbox_id))

        # PENDING — Odoo unavailable or the outcome was uncertain. Nothing
        # exists to read back; report what we know, honestly unsynced.
        return CreatedEntry(
            id=None,
            outbox_id=str(result.outbox_id),
            assignment_id=assignment_id,
            date=date,
            hours=hours,
            note=note,
            project_id=assignment.project_id,
            so_line_id=so_line_id,
            sync_state="pending",
        )

    async def update_entry(
        self, *, employee_id: int, odoo_line_id: int, assignment_id: str, date: str, hours: float, note: str
    ) -> CreatedEntry:
        existing_employee_id, existing_date = await self._read_existing_line(odoo_line_id)
        if existing_employee_id != employee_id:
            raise EntryNotOwned(f"employee {employee_id} does not own line {odoo_line_id}")

        hours_decimal = Decimal(str(hours))
        validate_increment(hours_decimal)

        assignment = await self._find_assignment(employee_id, assignment_id)

        entry_date = date_type.fromisoformat(date)
        start = date_type.fromisoformat(assignment.start_date) if assignment.start_date else None
        end = date_type.fromisoformat(assignment.end_date) if assignment.end_date else None
        validate_within_assignment(entry_date, start, end)

        # Both ends of a move matter: the line's current date (can't touch
        # a locked entry at all) and the new date (can't move it somewhere
        # locked either).
        await self._periods.guard(employee_id, existing_date)
        if entry_date != existing_date:
            await self._periods.guard(employee_id, entry_date)

        # Exclude this line's own current hours from "existing" — we're
        # replacing its value, not adding the new one on top of the old.
        existing_hours = await self._existing_hours(employee_id, entry_date, exclude_odoo_line_id=odoo_line_id)
        validate_daily_cap(existing_hours, hours_decimal, self._daily_hour_cap)

        so_line_id = assignment.so_line_id if assignment.kind == "paid" else None

        result = await self._outbox.enqueue_update(
            employee_id=employee_id,
            odoo_line_id=odoo_line_id,
            entry_date=entry_date,
            hours=hours_decimal,
            assignment_id=assignment_id,
            project_id=assignment.project_id,
            so_line_id=so_line_id,
            note=note,
        )

        if result.state is OutboxState.FAILED:
            raise _failure_for(result.last_error)

        if result.state is OutboxState.SYNCED:
            return await self._read_back(odoo_line_id, outbox_id=str(result.outbox_id))

        return CreatedEntry(
            id=odoo_line_id,
            outbox_id=str(result.outbox_id),
            assignment_id=assignment_id,
            date=date,
            hours=hours,
            note=note,
            project_id=assignment.project_id,
            so_line_id=so_line_id,
            sync_state="pending",
        )

    async def delete_entry(self, *, employee_id: int, odoo_line_id: int) -> str:
        """Returns the resulting sync_state ("synced" or "pending")."""
        existing_employee_id, existing_date = await self._read_existing_line(odoo_line_id)
        if existing_employee_id != employee_id:
            raise EntryNotOwned(f"employee {employee_id} does not own line {odoo_line_id}")

        await self._periods.guard(employee_id, existing_date)

        result = await self._outbox.enqueue_delete(
            employee_id=employee_id, odoo_line_id=odoo_line_id, entry_date=existing_date
        )

        if result.state is OutboxState.FAILED:
            raise _failure_for(result.last_error)

        return "synced" if result.state is OutboxState.SYNCED else "pending"

    async def search(
        self,
        *,
        employee_id: int,
        month: str | None,
        assignment_id: str | None,
        q: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[CreatedEntry], int]:
        """Step 2.6's "what did I do in June" listing — across periods,
        filterable, paginated. Reads Odoo directly, synced lines only: this
        is a retrospective report over confirmed history, not the live
        editing surface `list_for_employee_month` serves, so it
        deliberately doesn't overlay pending outbox rows the way that one
        does. A pending entry is still visible in the current month via
        the month view within seconds in the normal case; this listing
        exists for "what happened", not "what's in flight".
        """
        domain: list[tuple] = [("employee_id", "=", employee_id)]

        if month is not None:
            year_str, month_str = month.split("-")
            year, month_num = int(year_str), int(month_str)
            start_date = date_type(year, month_num, 1)
            end_date = date_type(year, month_num, calendar.monthrange(year, month_num)[1])
            domain += [("date", ">=", start_date.isoformat()), ("date", "<=", end_date.isoformat())]

        if assignment_id is not None:
            assignment = await self._find_assignment(employee_id, assignment_id)
            so_line_filter = assignment.so_line_id if assignment.kind == "paid" else False
            domain += [("project_id", "=", assignment.project_id), ("so_line", "=", so_line_filter)]

        if q:
            domain.append(("name", "ilike", q))

        total = await self._odoo.execute_kw("account.analytic.line", "search_count", [domain])
        records = await self._odoo.execute_kw(
            "account.analytic.line",
            "search_read",
            [domain],
            {
                "fields": ["date", "unit_amount", "name", "project_id", "so_line", self._profile.app_entry_id_field],
                "order": "date desc, id desc",
                "limit": limit,
                "offset": offset,
            },
        )
        return [self._to_entry(r) for r in records], total

    async def list_for_employee_month(self, employee_id: int, year: int, month: int) -> list[CreatedEntry]:
        start_date = date_type(year, month, 1)
        end_date = date_type(year, month, calendar.monthrange(year, month)[1])

        records = await self._odoo.execute_kw(
            "account.analytic.line",
            "search_read",
            [
                [
                    ("employee_id", "=", employee_id),
                    ("date", ">=", start_date.isoformat()),
                    ("date", "<=", end_date.isoformat()),
                ]
            ],
            {"fields": ["date", "unit_amount", "name", "project_id", "so_line", self._profile.app_entry_id_field]},
        )
        by_odoo_id: dict[int, CreatedEntry] = {r["id"]: self._to_entry(r) for r in records}

        pending_creates: list[CreatedEntry] = []
        for row in await self._outbox.rows_for_month(employee_id, start_date, end_date):
            if row.op == OutboxOp.CREATE.value:
                pending_creates.append(self._entry_from_outbox_row(row, sync_state=row.state))
            elif row.op == OutboxOp.UPDATE.value and row.state == OutboxState.PENDING.value:
                if row.odoo_line_id in by_odoo_id:
                    by_odoo_id[row.odoo_line_id] = self._entry_from_outbox_row(
                        row, sync_state="pending", odoo_line_id=row.odoo_line_id
                    )
            elif row.op == OutboxOp.DELETE.value and row.state == OutboxState.PENDING.value:
                by_odoo_id.pop(row.odoo_line_id, None)

        return list(by_odoo_id.values()) + pending_creates

    async def _existing_hours(
        self, employee_id: int, entry_date: date_type, *, exclude_odoo_line_id: int | None = None
    ) -> Decimal:
        records = await self._odoo.execute_kw(
            "account.analytic.line",
            "search_read",
            [[("employee_id", "=", employee_id), ("date", "=", entry_date.isoformat())]],
            {"fields": ["id", "unit_amount"]},
        )
        odoo_total = Decimal("0")
        for r in records:
            if exclude_odoo_line_id is not None and r["id"] == exclude_odoo_line_id:
                continue
            odoo_total += Decimal(str(r["unit_amount"]))
        pending_total = await self._outbox.pending_hours_for(employee_id, entry_date)
        return odoo_total + pending_total

    def _entry_from_outbox_row(
        self, row: OutboxRow, *, sync_state: str, odoo_line_id: int | None = None
    ) -> CreatedEntry:
        return CreatedEntry(
            id=odoo_line_id,
            outbox_id=str(row.id),
            assignment_id=row.assignment or "",
            date=row.entry_date.isoformat(),
            hours=float(row.hours) if row.hours is not None else 0.0,
            note=row.note or "",
            project_id=row.project_id,
            so_line_id=row.so_line_id,
            sync_state=sync_state,
        )

    def _to_entry(self, record: dict, *, outbox_id: str | None = None) -> CreatedEntry:
        project_id = record["project_id"][0]
        so_line_id = record["so_line"][0] if record["so_line"] else None
        if so_line_id is not None:
            assignment_id = f"project:{project_id}:paid"
        elif project_id == self._internal_project_id:
            assignment_id = "internal"
        else:
            assignment_id = f"project:{project_id}:unpaid"

        resolved_outbox_id = outbox_id or (record.get(self._profile.app_entry_id_field) or None)

        return CreatedEntry(
            id=record["id"],
            outbox_id=resolved_outbox_id,
            assignment_id=assignment_id,
            date=record["date"],
            hours=record["unit_amount"],
            note=record["name"],
            project_id=project_id,
            so_line_id=so_line_id,
            sync_state="synced",
        )

    async def _find_assignment(self, employee_id: int, assignment_id: str):
        assignments = await self._assignments.list_for_employee(employee_id)
        for a in assignments:
            if a.id == assignment_id:
                return a
        raise AssignmentNotHeld(f"employee {employee_id} does not hold assignment {assignment_id!r}")

    async def _read_existing_line(self, odoo_line_id: int) -> tuple[int, date_type]:
        records = await self._odoo.execute_kw(
            "account.analytic.line", "read", [[odoo_line_id]], {"fields": ["employee_id", "date"]}
        )
        if not records:
            raise EntryNotOwned(f"line {odoo_line_id} does not exist")
        record = records[0]
        return record["employee_id"][0], date_type.fromisoformat(record["date"])

    async def _read_back(self, line_id: int, *, outbox_id: str | None = None) -> CreatedEntry:
        # assignment_id isn't stored on the line — reconstruct it from
        # so_line/project_id the same way _to_entry does for a listing.
        # These always agree: it's the same identity scheme we just wrote.
        [record] = await self._odoo.execute_kw(
            "account.analytic.line",
            "read",
            [[line_id]],
            {"fields": ["date", "unit_amount", "name", "project_id", "so_line", self._profile.app_entry_id_field]},
        )
        return self._to_entry(record, outbox_id=outbox_id)
