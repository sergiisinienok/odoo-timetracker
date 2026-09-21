"""Assignment list-building — GET /api/assignments, step 1.4.

Validity dates: `assignment_start_source`/`assignment_end_source` in
odoo_profile.json are currently null — date enforcement was dropped by
owner decision, see docs/decisions/0005-no-assignment-validity-date-field.md
— so every assignment resolves open-ended today. If those profile keys
are ever populated, `_read_validity_dates` reads them from
sale.order.line (the documented preferred location) with no further code
changes needed, per that decision's own "Reversibility" note.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace

from tti.config import OdooProfile
from tti.odoo.client import OdooClient

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60
_UNPAID_LABEL_SUFFIX = " (unpaid)"
_INTERNAL_LABEL = "Internal"


@dataclass(frozen=True)
class Assignment:
    id: str
    kind: str  # "paid" | "unpaid" | "internal"
    project_id: int | None
    so_line_id: int | None
    label: str
    is_default: bool
    start_date: str | None
    end_date: str | None


class AssignmentService:
    def __init__(self, odoo: OdooClient, profile: OdooProfile, internal_project_id: int) -> None:
        self._odoo = odoo
        self._profile = profile
        self._internal_project_id = internal_project_id
        self._cache: dict[int, tuple[float, list[Assignment]]] = {}

    async def list_for_employee(self, employee_id: int) -> list[Assignment]:
        cached = self._cache.get(employee_id)
        if cached is not None:
            expires_at, assignments = cached
            if time.monotonic() < expires_at:
                return assignments

        assignments = await self._build(employee_id)
        self._cache[employee_id] = (time.monotonic() + _CACHE_TTL_SECONDS, assignments)
        return assignments

    async def _build(self, employee_id: int) -> list[Assignment]:
        rows = await self._odoo.execute_kw(
            "project.sale.line.employee.map",
            "search_read",
            [[("employee_id", "=", employee_id)]],
            {"fields": ["project_id", "sale_line_id"]},
        )

        project_ids = sorted({row["project_id"][0] for row in rows})
        projects: dict[int, dict] = {}
        if project_ids:
            records = await self._odoo.execute_kw(
                "project.project", "read", [project_ids], {"fields": ["name", "partner_id"]}
            )
            projects = {r["id"]: r for r in records}

        # A customer with more than one project in *this employee's own*
        # list needs the project name appended to stay unambiguous.
        customer_project_counts: dict[int, int] = {}
        for p in projects.values():
            if p["partner_id"]:
                customer_id = p["partner_id"][0]
                customer_project_counts[customer_id] = customer_project_counts.get(customer_id, 0) + 1

        def label_for(project: dict) -> str:
            if not project["partner_id"]:
                return project["name"]
            customer_name = project["partner_id"][1]
            if customer_project_counts[project["partner_id"][0]] > 1:
                return f"{customer_name} — {project['name']}"
            return customer_name

        assignments: list[Assignment] = []
        paid_project_ids: set[int] = set()
        for row in rows:
            project_id = row["project_id"][0]
            project = projects[project_id]
            so_line_id = row["sale_line_id"][0] if row["sale_line_id"] else None
            start_date, end_date = await self._read_validity_dates(so_line_id)
            base_label = label_for(project)

            assignments.append(
                Assignment(
                    id=f"project:{project_id}:paid",
                    kind="paid",
                    project_id=project_id,
                    so_line_id=so_line_id,
                    label=base_label,
                    is_default=False,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
            assignments.append(
                Assignment(
                    id=f"project:{project_id}:unpaid",
                    kind="unpaid",
                    project_id=project_id,
                    so_line_id=None,
                    label=base_label + _UNPAID_LABEL_SUFFIX,
                    is_default=False,
                    start_date=None,
                    end_date=None,
                )
            )
            paid_project_ids.add(project_id)

        assignments.append(
            Assignment(
                id="internal",
                kind="internal",
                project_id=self._internal_project_id,
                so_line_id=None,
                label=_INTERNAL_LABEL,
                is_default=False,
                start_date=None,
                end_date=None,
            )
        )

        return await self._apply_default(assignments, employee_id, paid_project_ids)

    async def _apply_default(
        self, assignments: list[Assignment], employee_id: int, paid_project_ids: set[int]
    ) -> list[Assignment]:
        [record] = await self._odoo.execute_kw(
            "hr.employee", "read", [[employee_id]], {"fields": [self._profile.default_project_field]}
        )
        default_value = record[self._profile.default_project_field]
        if not default_value:
            return assignments

        default_project_id = default_value[0]

        if default_project_id == self._internal_project_id:
            target_id = "internal"
        elif default_project_id in paid_project_ids:
            target_id = f"project:{default_project_id}:paid"
        else:
            logger.warning(
                "employee's default project is not in their assignment list — dropping it",
                extra={"employee_id": employee_id, "default_project_id": default_project_id},
            )
            return assignments

        return [replace(a, is_default=True) if a.id == target_id else a for a in assignments]

    async def _read_validity_dates(self, so_line_id: int | None) -> tuple[str | None, str | None]:
        start_source = self._profile.assignment_start_source
        end_source = self._profile.assignment_end_source
        if so_line_id is None or not (start_source or end_source):
            return None, None

        fields = [f for f in (start_source, end_source) if f]
        [record] = await self._odoo.execute_kw("sale.order.line", "read", [[so_line_id]], {"fields": fields})
        start = record.get(start_source) if start_source else None
        end = record.get(end_source) if end_source else None
        return start or None, end or None
