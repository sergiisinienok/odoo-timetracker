"""The catalog — GET /api/catalog, step 2b.6 (decision 0011).

Projects this employee may log against, each with its open tasks, read live
from Odoo. Replaces the assignment list: one entry per project (no paid/unpaid
twins), and **no billability anywhere** — the employee is never shown it; the
server resolves it at write time (domain/billing.py).

Which projects (decision 0014): every project the employee is mapped to (the
billable ones), plus **every active unbillable project that allows timesheets**,
whether or not they are mapped to it. There is no special "internal project":
an unbillable project is chosen by its own name, like any other. The one
exception is Odoo's own built-in company "Internal" project (`is_internal_project`):
Odoo hides it in its UI, so the app does too.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace

from tti.config import OdooProfile
from tti.domain.billing import TaskOverride, resolve_billing
from tti.lastknown import LastKnownCache
from tti.odoo.client import OdooClient
from tti.odoo.errors import OdooUnavailable, OdooUncertain

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60
_RECENT_LINES_LIMIT = 500


@dataclass(frozen=True)
class CatalogTask:
    id: int
    name: str


@dataclass(frozen=True)
class CatalogProject:
    id: int
    label: str
    tasks: tuple[CatalogTask, ...]
    is_default: bool
    last_used_task_id: int | None


@dataclass(frozen=True)
class Snapshot:
    """What one read of Odoo yields for an employee. `billing` is for the
    server's write path only and is never serialised: the employee is not
    shown billability (decision 0011). It is resolved at read time, so a save
    during an outage works from the last-known answer like everything else."""

    projects: list[CatalogProject]
    billing: dict[tuple[int, int], tuple[int | None, str | None]]  # (project, task) -> (so_line, warning)


class CatalogService:
    def __init__(self, odoo: OdooClient, profile: OdooProfile) -> None:
        self._odoo = odoo
        self._profile = profile
        self._cache: LastKnownCache[Snapshot] = LastKnownCache(ttl=_CACHE_TTL_SECONDS)
        # One build per employee at a time: the month view and the listings all
        # ask for the catalog at once, and Odoo answers in about a second a call.
        self._locks: dict[int, asyncio.Lock] = {}

    async def list_for_employee(self, employee_id: int) -> list[CatalogProject]:
        return (await self.snapshot(employee_id)).projects

    def invalidate(self, employee_id: int) -> None:
        """Expire the 60 s freshness (last-known is kept): after a write, the
        pre-filled "last used task" must reflect it on the next load."""
        self._cache.invalidate(employee_id)

    def peek(self, employee_id: int) -> Snapshot | None:
        """Whatever was last read for this employee, with no Odoo call — for
        courtesy uses such as labelling a listing, which must not wait on a build."""
        return self._cache.last_known(employee_id)

    async def snapshot(self, employee_id: int, *, fresh: bool = False) -> Snapshot:
        """`fresh=True` skips the 60 s cache — a save checks the task is open
        *now* — but still falls back to last-known when Odoo is unreachable."""
        if not fresh:
            cached = self._cache.fresh(employee_id)
            if cached is not None:
                return cached

        async with self._locks.setdefault(employee_id, asyncio.Lock()):
            if not fresh:
                # Another request may have built it while this one waited.
                cached = self._cache.fresh(employee_id)
                if cached is not None:
                    return cached
            try:
                catalog = await self._build(employee_id)
            except OdooUnavailable, OdooUncertain:
                # An outage must not stop someone saving an entry against a
                # project they could log on a minute ago (docs/decisions/0010).
                last_known = self._cache.last_known(employee_id)
                if last_known is None:
                    raise
                logger.warning("odoo unreachable — serving last-known catalog", extra={"employee_id": employee_id})
                return last_known
            self._cache.put(employee_id, catalog)
            return catalog

    async def _build(self, employee_id: int) -> Snapshot:
        billable_field = self._profile.project_billable_field
        fields = ["name", "partner_id", billable_field]

        # Three stages, each a set of independent Odoo calls run together.
        rows, unbillable, default_value = await asyncio.gather(
            self._odoo.execute_kw(
                "project.sale.line.employee.map",
                "search_read",
                [[("employee_id", "=", employee_id)]],
                {"fields": ["project_id", "sale_line_id"], "order": "id"},
            ),
            self._odoo.execute_kw(
                "project.project",
                "search_read",
                [
                    [
                        (billable_field, "=", False),
                        (self._profile.project_timesheets_field, "=", True),
                        # Odoo's own built-in company "Internal" project is hidden in its UI; so is it here.
                        (self._profile.project_internal_field, "=", False),
                    ]
                ],
                {"fields": fields, "order": "name, id"},
            ),
            self._default_project(employee_id),
        )
        mapped_so_line: dict[int, int] = {}
        for row in rows:
            if row["sale_line_id"]:
                mapped_so_line.setdefault(row["project_id"][0], row["sale_line_id"][0])
        mapped_ids = sorted({row["project_id"][0] for row in rows})

        # search_read, not read: an archived project drops out of the list.
        mapped = await self._odoo.execute_kw(
            "project.project", "search_read", [[("id", "in", mapped_ids)]], {"fields": fields}
        )
        projects = {r["id"]: r for r in [*unbillable, *mapped]}
        # Mapped projects first, in id order; then the other unbillable ones by name.
        project_ids = [r["id"] for r in sorted(mapped, key=lambda r: r["id"])]
        project_ids += [r["id"] for r in unbillable if r["id"] not in set(project_ids)]

        (tasks_by_project, overrides), latest_task = await asyncio.gather(
            self._open_tasks(project_ids), self._latest_tasks(employee_id, project_ids)
        )
        # The task last used on a project is offered only while it is still open there.
        last_used = {
            pid: task_id
            for pid, task_id in latest_task.items()
            if any(t.id == task_id for t in tasks_by_project.get(pid, []))
        }

        # Billable projects are named for their client; a customer with more
        # than one of them in *this employee's own* list needs the project name
        # appended to stay unambiguous. An unbillable project is chosen by its
        # own name (decision 0014).
        customer_counts: dict[int, int] = {}
        for pid in project_ids:
            partner = projects[pid]["partner_id"]
            if projects[pid][billable_field] and partner:
                customer_counts[partner[0]] = customer_counts.get(partner[0], 0) + 1

        def label_for(pid: int) -> str:
            project = projects[pid]
            partner = project["partner_id"]
            if not partner or not project[billable_field]:
                return project["name"]
            if customer_counts[partner[0]] > 1:
                return f"{partner[1]} — {project['name']}"
            return partner[1]

        catalog = [
            CatalogProject(
                id=pid,
                label=label_for(pid),
                tasks=tuple(tasks_by_project.get(pid, [])),
                is_default=False,
                last_used_task_id=last_used.get(pid),
            )
            for pid in project_ids
        ]
        billing = {
            (pid, task.id): resolve_billing(
                bool(projects[pid][billable_field]),
                overrides[task.id],
                mapped_so_line.get(pid),
            )
            for pid in project_ids
            for task in tasks_by_project.get(pid, [])
        }
        return Snapshot(projects=self._apply_default(catalog, employee_id, default_value), billing=billing)

    def _override_for(self, raw: str | bool) -> TaskOverride:
        # The Odoo boundary: the task's selection value -> TaskOverride. Blank
        # (tasks that predate the field) means same-as-project.
        if raw == self._profile.task_billable_yes_value:
            return TaskOverride.BILLABLE
        if raw == self._profile.task_billable_no_value:
            return TaskOverride.NOT_BILLABLE
        return TaskOverride.SAME_AS_PROJECT

    async def _open_tasks(self, project_ids: list[int]) -> tuple[dict[int, list[CatalogTask]], dict[int, TaskOverride]]:
        if not project_ids:
            return {}, {}
        domain = [("project_id", "in", project_ids), *[tuple(term) for term in self._profile.task_open_domain]]
        records = await self._odoo.execute_kw(
            "project.task",
            "search_read",
            [domain],
            {"fields": ["name", "project_id", self._profile.task_billable_field], "order": "sequence, id"},
        )
        tasks: dict[int, list[CatalogTask]] = {}
        overrides: dict[int, TaskOverride] = {}
        for r in records:
            tasks.setdefault(r["project_id"][0], []).append(CatalogTask(id=r["id"], name=r["name"]))
            overrides[r["id"]] = self._override_for(r[self._profile.task_billable_field])
        return tasks, overrides

    async def _latest_tasks(self, employee_id: int, project_ids: list[int]) -> dict[int, int]:
        """The task on the employee's most recent line, per project."""
        if not project_ids:
            return {}
        lines = await self._odoo.execute_kw(
            "account.analytic.line",
            "search_read",
            [[("employee_id", "=", employee_id), ("project_id", "in", project_ids), ("task_id", "!=", False)]],
            {"fields": ["project_id", "task_id"], "order": "date desc, id desc", "limit": _RECENT_LINES_LIMIT},
        )
        latest: dict[int, int] = {}
        for line in lines:
            latest.setdefault(line["project_id"][0], line["task_id"][0])
        return latest

    async def _default_project(self, employee_id: int):
        [record] = await self._odoo.execute_kw(
            "hr.employee", "read", [[employee_id]], {"fields": [self._profile.default_project_field]}
        )
        return record[self._profile.default_project_field]

    def _apply_default(self, catalog: list[CatalogProject], employee_id: int, default_value) -> list[CatalogProject]:
        if not default_value:
            return catalog
        default_project_id = default_value[0]
        if default_project_id not in {p.id for p in catalog}:
            logger.warning(
                "employee's default project is not in their catalog — dropping it",
                extra={"employee_id": employee_id, "default_project_id": default_project_id},
            )
            return catalog
        return [replace(p, is_default=True) if p.id == default_project_id else p for p in catalog]
