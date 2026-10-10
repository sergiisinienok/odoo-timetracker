"""Entry creation, editing, deletion, and listing — steps 1.5 and 2.3/2.4.

Every mutation goes through the outbox (step 2.3): validate, then hand
off to OutboxService, which enqueues as pending and attempts the Odoo
write inline. A synced result gets an honest read-back from Odoo — "the
app never claims a write succeeded on the strength of its own optimism"
(step 1.5) — a pending result is reported from what we know ourselves,
honestly marked not-yet-synced.

Guards, in the order step 2.4 specifies — "employee owns the line,
period is open, project is held, increment is valid, daily cap holds
including pending rows" — plus, since Phase 2b, that the task is required,
belongs to the project and is open (decision 0011). Applied per operation:
create has no existing line to own, so that check is moot; delete doesn't
propose new hours/date/project/task, so project/task/increment/cap don't
apply to it.

Billing is never asked of the employee. The server resolves `so_line` from
project and task (domain/billing.py) when a line is created or its project or
task changes, and never writes it over an approver's override — recognised by
Odoo's own manual-edit marker (profile.so_line_manual_marker_field).

`name` defaults to a single space when the note is empty — the plan
flagged "Odoo dislikes empty descriptions" as *(verify)*; live-checked
in step 1.5 and an empty string actually works fine on this instance,
but the space default costs nothing and matches what the plan asks for.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal

from tti.catalog.service import CatalogService, Snapshot
from tti.config import OdooProfile
from tti.domain.daily_cap import validate_daily_cap
from tti.domain.increments import validate_increment
from tti.entries.errors import (
    BillingSetByApprover,
    EntryNotOwned,
    ProjectNotHeld,
    TaskNotInProject,
    TaskNotOpen,
    TaskRequired,
)
from tti.lastknown import LastKnownCache
from tti.odoo.client import OdooClient
from tti.odoo.errors import OdooUnavailable, OdooUncertain
from tti.outbox.errors import OdooWriteRejected
from tti.outbox.models import OutboxOp, OutboxRow, OutboxState
from tti.outbox.service import PERIOD_LOCKED_PREFIX, OutboxService
from tti.periods.errors import PeriodLocked
from tti.periods.service import PeriodService

logger = logging.getLogger(__name__)


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
    project_id: int
    project_label: str
    task_id: int | None  # None for lines logged before Phase 2b ("No task")
    task_name: str | None
    date: str
    hours: float
    note: str
    sync_state: str  # "synced" | "pending" | "failed"
    # Server-side only, never serialised: set when a line resolved billable but
    # the employee has no order line on the project (decision 0012).
    billing_warning: str | None = None


@dataclass(frozen=True)
class _ExistingLine:
    employee_id: int
    date: date_type
    project_id: int
    task_id: int | None
    so_line_id: int | None
    overridden: bool


class EntryService:
    def __init__(
        self,
        odoo: OdooClient,
        profile: OdooProfile,
        catalog: CatalogService,
        periods: PeriodService,
        outbox: OutboxService,
        internal_project_id: int,
        daily_hour_cap: Decimal,
    ) -> None:
        self._odoo = odoo
        self._profile = profile
        self._catalog = catalog
        self._periods = periods
        self._outbox = outbox
        self._internal_project_id = internal_project_id
        self._daily_hour_cap = daily_hour_cap
        # (employee, date) -> the Odoo lines on that day as (line id, hours),
        # as last seen. Only consulted when Odoo cannot be asked — see
        # docs/decisions/0010, gap 2. ttl=0: never "fresh", every save still
        # reads live first.
        self._day_lines: LastKnownCache[list[tuple[int, Decimal]]] = LastKnownCache(ttl=0)

    async def create_entry(
        self, *, employee_id: int, project_id: int, task_id: int | None, date: str, hours: float, note: str
    ) -> CreatedEntry:
        # Convert at the boundary: domain rules work in Decimal/date, the
        # rest of this service and the API layer stay in the JSON-native
        # str/float shapes. str(hours) first, never Decimal(hours) direct
        # — see domain/increments.py's own note on why.
        hours_decimal = Decimal(str(hours))
        validate_increment(hours_decimal)

        snapshot = await self._catalog.snapshot(employee_id, fresh=True)
        task = await self._check_project_and_task(snapshot, project_id, task_id)

        entry_date = date_type.fromisoformat(date)
        await self._periods.guard(employee_id, entry_date)

        existing_hours = await self._existing_hours(employee_id, entry_date)
        validate_daily_cap(existing_hours, hours_decimal, self._daily_hour_cap)

        # Unbillable lines get so_line=False written explicitly — the
        # unpaid_recipe, re-proven with a task set in step 2b.3.
        so_line_id, warning = snapshot.billing[(project_id, task)]

        result = await self._outbox.enqueue_create(
            employee_id=employee_id,
            entry_date=entry_date,
            hours=hours_decimal,
            project_id=project_id,
            task_id=task,
            so_line_id=so_line_id,
            note=note,
        )

        if result.state is OutboxState.FAILED:
            raise _failure_for(result.last_error)

        if result.state is OutboxState.SYNCED:
            assert result.odoo_line_id is not None
            entry = await self._read_back(
                employee_id, result.odoo_line_id, outbox_id=str(result.outbox_id), warning=warning
            )
            self._remember_line(employee_id, entry_date, result.odoo_line_id, hours_decimal)
            return entry

        # PENDING — Odoo unavailable or the outcome was uncertain. Nothing
        # exists to read back; report what we know, honestly unsynced.
        return self._pending_entry(
            snapshot, outbox_id=str(result.outbox_id), line_id=None, project_id=project_id, task_id=task,
            date=date, hours=hours, note=note, warning=warning,
        )  # fmt: skip

    async def update_entry(
        self,
        *,
        employee_id: int,
        odoo_line_id: int,
        project_id: int,
        task_id: int | None,
        date: str,
        hours: float,
        note: str,
    ) -> CreatedEntry:
        existing = await self._read_existing_line(odoo_line_id)
        if existing.employee_id != employee_id:
            raise EntryNotOwned(f"employee {employee_id} does not own line {odoo_line_id}")

        hours_decimal = Decimal(str(hours))
        validate_increment(hours_decimal)

        snapshot = await self._catalog.snapshot(employee_id, fresh=True)
        if task_id is None:
            raise TaskRequired("choose a task for this entry")

        moved = (project_id, task_id) != (existing.project_id, existing.task_id)
        if moved:
            # An approver's override is a decision about this line's work.
            if existing.overridden:
                raise BillingSetByApprover(
                    "the approver has set how this line is billed; ask them to move it to another task"
                )
            await self._check_project_and_task(snapshot, project_id, task_id)
        # An unmoved line stays editable (hours, date, note) even if its task
        # has since closed or the project left the employee's list: closing a
        # task must not stop someone correcting an old line in an open month.

        entry_date = date_type.fromisoformat(date)

        # Both ends of a move matter: the line's current date (can't touch
        # a locked entry at all) and the new date (can't move it somewhere
        # locked either).
        await self._periods.guard(employee_id, existing.date)
        if entry_date != existing.date:
            await self._periods.guard(employee_id, entry_date)

        # Exclude this line's own current hours from "existing" — we're
        # replacing its value, not adding the new one on top of the old.
        existing_hours = await self._existing_hours(employee_id, entry_date, exclude_odoo_line_id=odoo_line_id)
        validate_daily_cap(existing_hours, hours_decimal, self._daily_hour_cap)

        # Billing is re-resolved only when project or task changed, and never
        # over an override (refused above). Otherwise Odoo's own value stands.
        so_line_id, warning = snapshot.billing[(project_id, task_id)] if moved else (None, None)

        result = await self._outbox.enqueue_update(
            employee_id=employee_id,
            odoo_line_id=odoo_line_id,
            entry_date=entry_date,
            hours=hours_decimal,
            project_id=project_id,
            task_id=task_id,
            so_line_id=so_line_id,
            write_billing=moved,
            note=note,
        )

        if result.state is OutboxState.FAILED:
            raise _failure_for(result.last_error)

        if result.state is OutboxState.SYNCED:
            self._forget_line(employee_id, existing.date, odoo_line_id)
            self._remember_line(employee_id, entry_date, odoo_line_id, hours_decimal)
            return await self._read_back(employee_id, odoo_line_id, outbox_id=str(result.outbox_id), warning=warning)

        return self._pending_entry(
            snapshot, outbox_id=str(result.outbox_id), line_id=odoo_line_id, project_id=project_id, task_id=task_id,
            date=date, hours=hours, note=note, warning=warning,
        )  # fmt: skip

    async def delete_entry(self, *, employee_id: int, odoo_line_id: int) -> str:
        """Returns the resulting sync_state ("synced" or "pending")."""
        existing = await self._read_existing_line(odoo_line_id)
        if existing.employee_id != employee_id:
            raise EntryNotOwned(f"employee {employee_id} does not own line {odoo_line_id}")

        await self._periods.guard(employee_id, existing.date)

        result = await self._outbox.enqueue_delete(
            employee_id=employee_id, odoo_line_id=odoo_line_id, entry_date=existing.date
        )

        if result.state is OutboxState.FAILED:
            raise _failure_for(result.last_error)

        if result.state is OutboxState.SYNCED:
            self._forget_line(employee_id, existing.date, odoo_line_id)
            return "synced"
        return "pending"

    async def search(
        self,
        *,
        employee_id: int,
        month: str | None,
        project_id: int | None,
        task_id: int | None,
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

        if project_id is not None:
            domain.append(("project_id", "=", project_id))
        if task_id is not None:
            domain.append(("task_id", "=", task_id))

        if q:
            domain.append(("name", "ilike", q))

        total = await self._odoo.execute_kw("account.analytic.line", "search_count", [domain])
        records = await self._odoo.execute_kw(
            "account.analytic.line",
            "search_read",
            [domain],
            {
                "fields": self._line_fields(),
                "order": "date desc, id desc",
                "limit": limit,
                "offset": offset,
            },
        )
        snapshot = await self._snapshot_or_none(employee_id)
        return [self._to_entry(r, snapshot) for r in records], total

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
            {"fields": self._line_fields()},
        )
        snapshot = await self._snapshot_or_none(employee_id)
        by_odoo_id: dict[int, CreatedEntry] = {r["id"]: self._to_entry(r, snapshot) for r in records}

        # A month load is the freshest view of every day in it — including days
        # with no lines, which is knowledge too (0 h).
        per_day: dict[date_type, list[tuple[int, Decimal]]] = {
            date_type(year, month, d): [] for d in range(1, calendar.monthrange(year, month)[1] + 1)
        }
        for r in records:
            per_day[date_type.fromisoformat(r["date"])].append((r["id"], Decimal(str(r["unit_amount"]))))
        for day, lines in per_day.items():
            self._day_lines.put((employee_id, day), lines)

        pending_creates: list[CreatedEntry] = []
        for row in await self._outbox.rows_for_month(employee_id, start_date, end_date):
            if row.op == OutboxOp.CREATE.value:
                pending_creates.append(self._entry_from_outbox_row(row, snapshot, sync_state=row.state))
            elif row.op == OutboxOp.UPDATE.value and row.state == OutboxState.PENDING.value:
                if row.odoo_line_id in by_odoo_id:
                    by_odoo_id[row.odoo_line_id] = self._entry_from_outbox_row(
                        row, snapshot, sync_state="pending", odoo_line_id=row.odoo_line_id
                    )
            elif row.op == OutboxOp.DELETE.value and row.state == OutboxState.PENDING.value:
                by_odoo_id.pop(row.odoo_line_id, None)

        return list(by_odoo_id.values()) + pending_creates

    async def _existing_hours(
        self, employee_id: int, entry_date: date_type, *, exclude_odoo_line_id: int | None = None
    ) -> Decimal:
        try:
            records = await self._odoo.execute_kw(
                "account.analytic.line",
                "search_read",
                [[("employee_id", "=", employee_id), ("date", "=", entry_date.isoformat())]],
                {"fields": ["id", "unit_amount"]},
            )
        except OdooUnavailable, OdooUncertain:
            # An outage must not refuse an entry over a limit check. Fall back
            # to the day as last seen; with no last-known view the limit
            # cannot be checked at all, and refusing is the only honest answer.
            last_known = self._day_lines.last_known((employee_id, entry_date))
            if last_known is None:
                raise
            logger.warning(
                "odoo unreachable — daily cap checked against last-known hours",
                extra={"employee_id": employee_id, "date": entry_date.isoformat()},
            )
            lines = last_known
        else:
            lines = [(r["id"], Decimal(str(r["unit_amount"]))) for r in records]
            self._day_lines.put((employee_id, entry_date), lines)

        odoo_total = sum((h for line_id, h in lines if line_id != exclude_odoo_line_id), Decimal(0))
        pending_total = await self._outbox.pending_hours_for(employee_id, entry_date)
        return odoo_total + pending_total

    def _remember_line(self, employee_id: int, day: date_type, line_id: int, hours: Decimal) -> None:
        """Keep the last-known day in step with our own synced writes, so the
        next outage does not undercount hours we ourselves just wrote. A day
        never seen is left unknown rather than guessed."""
        lines = self._day_lines.last_known((employee_id, day))
        if lines is not None:
            self._day_lines.put((employee_id, day), [(i, h) for i, h in lines if i != line_id] + [(line_id, hours)])

    def _forget_line(self, employee_id: int, day: date_type, line_id: int) -> None:
        lines = self._day_lines.last_known((employee_id, day))
        if lines is not None:
            self._day_lines.put((employee_id, day), [(i, h) for i, h in lines if i != line_id])

    def _line_fields(self) -> list[str]:
        return ["date", "unit_amount", "name", "project_id", "task_id", self._profile.app_entry_id_field]

    async def _snapshot_or_none(self, employee_id: int) -> Snapshot | None:
        """Labels are a courtesy: a listing must not fail because the catalog
        could not be read, so fall back to Odoo's own names."""
        try:
            return await self._catalog.snapshot(employee_id)
        except OdooUnavailable, OdooUncertain:
            return None

    @staticmethod
    def _labels(snapshot: Snapshot | None, project_id: int, task_id: int | None, odoo_names: tuple[str, str | None]):
        project_label, task_name = odoo_names
        if snapshot is not None:
            project = next((p for p in snapshot.projects if p.id == project_id), None)
            if project is not None:
                project_label = project.label
                task = next((t for t in project.tasks if t.id == task_id), None)
                if task is not None:
                    task_name = task.name
        return project_label, task_name

    def _pending_entry(
        self,
        snapshot: Snapshot,
        *,
        outbox_id: str,
        line_id: int | None,
        project_id: int,
        task_id: int | None,
        date: str,
        hours: float,
        note: str,
        warning: str | None,
    ) -> CreatedEntry:
        project_label, task_name = self._labels(snapshot, project_id, task_id, (f"project {project_id}", None))
        return CreatedEntry(
            id=line_id,
            outbox_id=outbox_id,
            project_id=project_id,
            project_label=project_label,
            task_id=task_id,
            task_name=task_name,
            date=date,
            hours=hours,
            note=note,
            sync_state="pending",
            billing_warning=warning,
        )

    def _entry_from_outbox_row(
        self, row: OutboxRow, snapshot: Snapshot | None, *, sync_state: str, odoo_line_id: int | None = None
    ) -> CreatedEntry:
        project_label, task_name = self._labels(
            snapshot, row.project_id, row.task_id, (f"project {row.project_id}", None)
        )
        return CreatedEntry(
            id=odoo_line_id,
            outbox_id=str(row.id),
            project_id=row.project_id,
            project_label=project_label,
            task_id=row.task_id,
            task_name=task_name,
            date=row.entry_date.isoformat(),
            hours=float(row.hours) if row.hours is not None else 0.0,
            note=row.note or "",
            sync_state=sync_state,
        )

    def _to_entry(
        self, record: dict, snapshot: Snapshot | None, *, outbox_id: str | None = None, warning: str | None = None
    ) -> CreatedEntry:
        project_id, odoo_project_name = record["project_id"]
        task_id, odoo_task_name = record["task_id"] if record["task_id"] else (None, None)
        project_label, task_name = self._labels(snapshot, project_id, task_id, (odoo_project_name, odoo_task_name))
        resolved_outbox_id = outbox_id or (record.get(self._profile.app_entry_id_field) or None)

        return CreatedEntry(
            id=record["id"],
            outbox_id=resolved_outbox_id,
            project_id=project_id,
            project_label=project_label,
            task_id=task_id,
            task_name=task_name,
            date=record["date"],
            hours=record["unit_amount"],
            note=record["name"],
            sync_state="synced",
            billing_warning=warning,
        )

    async def _check_project_and_task(self, snapshot: Snapshot, project_id: int, task_id: int | None) -> int:
        """Project held, task given, in the project, open. Returns the task id."""
        project = next((p for p in snapshot.projects if p.id == project_id), None)
        if project is None:
            raise ProjectNotHeld(f"you are not assigned to project {project_id}")
        if task_id is None:
            raise TaskRequired("choose a task for this entry")
        if any(t.id == task_id for t in project.tasks):
            return task_id

        # Not on the project's open list: say why, rather than a bare refusal.
        try:
            records = await self._odoo.execute_kw(
                "project.task",
                "search_read",
                [[("id", "=", task_id), ("active", "in", [True, False])]],
                {"fields": ["project_id"]},
            )
        except OdooUnavailable, OdooUncertain:
            records = []
        if records and records[0]["project_id"] and records[0]["project_id"][0] != project_id:
            raise TaskNotInProject(f"task {task_id} does not belong to project {project_id}")
        raise TaskNotOpen(f"task {task_id} is closed or archived and cannot be logged against")

    async def _read_existing_line(self, odoo_line_id: int) -> _ExistingLine:
        marker = self._profile.so_line_manual_marker_field
        records = await self._odoo.execute_kw(
            "account.analytic.line",
            "read",
            [[odoo_line_id]],
            {"fields": ["employee_id", "date", "project_id", "task_id", "so_line", marker]},
        )
        if not records:
            raise EntryNotOwned(f"line {odoo_line_id} does not exist")
        r = records[0]
        return _ExistingLine(
            employee_id=r["employee_id"][0],
            date=date_type.fromisoformat(r["date"]),
            project_id=r["project_id"][0],
            task_id=r["task_id"][0] if r["task_id"] else None,
            so_line_id=r["so_line"][0] if r["so_line"] else None,
            overridden=bool(r[marker]),
        )

    async def _read_back(
        self, employee_id: int, line_id: int, *, outbox_id: str | None = None, warning: str | None = None
    ) -> CreatedEntry:
        [record] = await self._odoo.execute_kw(
            "account.analytic.line", "read", [[line_id]], {"fields": self._line_fields()}
        )
        snapshot = await self._snapshot_or_none(employee_id)
        return self._to_entry(record, snapshot, outbox_id=outbox_id, warning=warning)
