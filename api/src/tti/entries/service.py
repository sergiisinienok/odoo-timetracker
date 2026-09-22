"""Entry creation and listing — steps 1.5 and 2.3.

Creation goes through the outbox now (step 2.3): validate, then hand off
to OutboxService.enqueue_create, which enqueues as pending and attempts
the Odoo write inline. A synced result gets an honest read-back from
Odoo — "the app never claims a write succeeded on the strength of its
own optimism" (step 1.5) — a pending result is reported from what we
know ourselves, honestly marked not-yet-synced, because there's nothing
in Odoo yet to read back.

`name` defaults to a single space when the note is empty — the plan
flagged "Odoo dislikes empty descriptions" as *(verify)*; live-checked
in step 1.5 and an empty string actually works fine on this instance,
but the space default costs nothing and matches what the plan asks for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal

from tti.assignments.service import AssignmentService
from tti.config import OdooProfile
from tti.domain.increments import validate_increment
from tti.domain.validity import validate_within_assignment
from tti.entries.errors import AssignmentNotHeld
from tti.odoo.client import OdooClient
from tti.outbox.errors import OdooWriteRejected
from tti.outbox.models import OutboxState
from tti.outbox.service import OutboxService
from tti.periods.service import PeriodService


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
    sync_state: str  # "synced" | "pending"


class EntryService:
    def __init__(
        self,
        odoo: OdooClient,
        profile: OdooProfile,
        assignments: AssignmentService,
        periods: PeriodService,
        outbox: OutboxService,
        internal_project_id: int,
    ) -> None:
        self._odoo = odoo
        self._profile = profile
        self._assignments = assignments
        self._periods = periods
        self._outbox = outbox
        self._internal_project_id = internal_project_id

    async def create_entry(
        self, *, employee_id: int, assignment_id: str, date: str, hours: float, note: str
    ) -> CreatedEntry:
        # Convert at the boundary: domain rules work in Decimal/date, the
        # rest of this service and the API layer stay in the JSON-native
        # str/float shapes. str(hours) first, never Decimal(hours) direct
        # — see domain/increments.py's own note on why.
        validate_increment(Decimal(str(hours)))

        assignment = await self._find_assignment(employee_id, assignment_id)

        entry_date = date_type.fromisoformat(date)
        start = date_type.fromisoformat(assignment.start_date) if assignment.start_date else None
        end = date_type.fromisoformat(assignment.end_date) if assignment.end_date else None
        validate_within_assignment(entry_date, start, end)

        await self._periods.guard(employee_id, entry_date)

        # Paid gets the real sale order line; unpaid and internal both
        # write so_line=False explicitly — the unpaid_recipe confirmed in
        # Phase 0 (odoo_profile.json: "create() with so_line=False passed
        # explicitly").
        so_line_id = assignment.so_line_id if assignment.kind == "paid" else None

        result = await self._outbox.enqueue_create(
            employee_id=employee_id,
            entry_date=entry_date,
            hours=Decimal(str(hours)),
            assignment_id=assignment_id,
            project_id=assignment.project_id,
            so_line_id=so_line_id,
            note=note,
        )

        if result.state is OutboxState.FAILED:
            raise OdooWriteRejected(result.last_error or "Odoo rejected the write")

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

    async def list_for_employee_on_date(self, employee_id: int, date: str) -> list[CreatedEntry]:
        records = await self._odoo.execute_kw(
            "account.analytic.line",
            "search_read",
            [[("employee_id", "=", employee_id), ("date", "=", date)]],
            {"fields": ["date", "unit_amount", "name", "project_id", "so_line", self._profile.app_entry_id_field]},
        )
        return [self._to_entry(r) for r in records]

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
