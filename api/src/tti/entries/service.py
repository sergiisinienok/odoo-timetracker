"""Write-through entry creation — POST /api/entries, step 1.5.

No queue yet: a synchronous create against Odoo. The response is built
from a read-back of the created line, never from the request body — "the
app never claims a write succeeded on the strength of its own optimism."
(step 1.5)

`name` defaults to a single space when the note is empty — the plan
flagged "Odoo dislikes empty descriptions" as *(verify)*; live-checked
here and an empty string actually works fine on this instance, but the
space default costs nothing and matches what the plan asks for, so it
stays as a cheap safety margin rather than a proven necessity.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from tti.assignments.service import AssignmentService
from tti.config import OdooProfile
from tti.domain.increments import is_valid_increment
from tti.domain.validity import is_date_within_validity
from tti.entries.errors import AssignmentNotHeld, AssignmentNotValidOnDate, InvalidIncrement
from tti.odoo.client import OdooClient


@dataclass(frozen=True)
class CreatedEntry:
    id: int
    assignment_id: str
    date: str
    hours: float
    note: str
    project_id: int
    so_line_id: int | None


class EntryService:
    def __init__(
        self, odoo: OdooClient, profile: OdooProfile, assignments: AssignmentService, internal_project_id: int
    ) -> None:
        self._odoo = odoo
        self._profile = profile
        self._assignments = assignments
        self._internal_project_id = internal_project_id

    async def create_entry(
        self, *, employee_id: int, assignment_id: str, date: str, hours: float, note: str
    ) -> CreatedEntry:
        if not is_valid_increment(hours):
            raise InvalidIncrement(f"{hours} is not a positive multiple of 0.25")

        assignment = await self._find_assignment(employee_id, assignment_id)

        if not is_date_within_validity(date, assignment.start_date, assignment.end_date):
            raise AssignmentNotValidOnDate(f"{date} is outside this assignment's validity window")

        # Paid gets the real sale order line; unpaid and internal both
        # write so_line=False explicitly — the unpaid_recipe confirmed in
        # Phase 0 (odoo_profile.json: "create() with so_line=False passed
        # explicitly").
        so_line_id: int | bool = assignment.so_line_id if assignment.kind == "paid" else False

        vals = {
            "date": date,
            "employee_id": employee_id,
            "project_id": assignment.project_id,
            "unit_amount": hours,
            "name": note or " ",
            "so_line": so_line_id,
            self._profile.app_entry_id_field: str(uuid.uuid4()),
        }
        line_id = await self._odoo.execute_kw("account.analytic.line", "create", [vals])

        return await self._read_back(line_id)

    async def list_for_employee_on_date(self, employee_id: int, date: str) -> list[CreatedEntry]:
        records = await self._odoo.execute_kw(
            "account.analytic.line",
            "search_read",
            [[("employee_id", "=", employee_id), ("date", "=", date)]],
            {"fields": ["date", "unit_amount", "name", "project_id", "so_line"]},
        )
        return [self._to_entry(r) for r in records]

    def _to_entry(self, record: dict) -> CreatedEntry:
        project_id = record["project_id"][0]
        so_line_id = record["so_line"][0] if record["so_line"] else None
        if so_line_id is not None:
            assignment_id = f"project:{project_id}:paid"
        elif project_id == self._internal_project_id:
            assignment_id = "internal"
        else:
            assignment_id = f"project:{project_id}:unpaid"

        return CreatedEntry(
            id=record["id"],
            assignment_id=assignment_id,
            date=record["date"],
            hours=record["unit_amount"],
            note=record["name"],
            project_id=project_id,
            so_line_id=so_line_id,
        )

    async def _find_assignment(self, employee_id: int, assignment_id: str):
        assignments = await self._assignments.list_for_employee(employee_id)
        for a in assignments:
            if a.id == assignment_id:
                return a
        raise AssignmentNotHeld(f"employee {employee_id} does not hold assignment {assignment_id!r}")

    async def _read_back(self, line_id: int) -> CreatedEntry:
        # assignment_id isn't stored on the line — reconstruct it from
        # so_line/project_id the same way _to_entry does for a listing.
        # These always agree: it's the same identity scheme we just wrote.
        [record] = await self._odoo.execute_kw(
            "account.analytic.line",
            "read",
            [[line_id]],
            {"fields": ["date", "unit_amount", "name", "project_id", "so_line"]},
        )
        return self._to_entry(record)
