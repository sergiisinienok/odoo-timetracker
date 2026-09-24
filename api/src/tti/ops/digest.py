"""Daily ops digest — step 2.7.

Four things ops should hear about before employees do:
  1. outbox rows pending for more than 15 minutes
  2. every failed outbox row
  3. active employees with no assignment
  4. active employees with no entry in the last 5 working days

Built from the app's own Postgres (1, 2) and Odoo (3, 4), sent through
Odoo's mail.mail — see docs/decisions/0009 for the access grant that needs.
The digest never carries a rate or amount; it doesn't read them.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tti.odoo.client import OdooClient
from tti.outbox.models import OutboxRow, OutboxState

logger = logging.getLogger(__name__)

PENDING_AGE_LIMIT = timedelta(minutes=15)
WORKING_DAYS_WINDOW = 5
_ERROR_MAX_CHARS = 200


@dataclass(frozen=True)
class OutboxItem:
    employee: str
    entry_date: date
    op: str
    attempts: int
    age_minutes: int
    last_error: str | None


@dataclass(frozen=True)
class Digest:
    stuck_pending: list[OutboxItem] = field(default_factory=list)
    failed: list[OutboxItem] = field(default_factory=list)
    no_assignment: list[str] = field(default_factory=list)
    no_recent_entry: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.stuck_pending or self.failed or self.no_assignment or self.no_recent_entry)


def last_working_days(today: date, count: int = WORKING_DAYS_WINDOW) -> list[date]:
    """The `count` weekdays before `today`, newest first. Public holidays are
    not modelled — an employee on one still shows as quiet, which is the
    conservative direction for a digest."""
    days: list[date] = []
    day = today
    while len(days) < count:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            days.append(day)
    return days


def render(digest: Digest, today: date) -> tuple[str, str]:
    """(subject, html body)."""
    problems = (
        len(digest.stuck_pending) + len(digest.failed) + len(digest.no_assignment) + len(digest.no_recent_entry)
    )
    subject = (
        f"Time tracker digest {today.isoformat()}: all clear"
        if digest.is_empty
        else f"Time tracker digest {today.isoformat()}: {problems} item(s) need attention"
    )

    def outbox_section(title: str, items: list[OutboxItem]) -> str:
        if not items:
            return f"<h3>{title}</h3><p>None.</p>"
        rows = "".join(
            f"<li>{html.escape(i.employee)} — {i.entry_date.isoformat()} ({i.op}), "
            f"{i.attempts} attempt(s), {i.age_minutes} min old"
            + (f": {html.escape(i.last_error[:_ERROR_MAX_CHARS])}" if i.last_error else "")
            + "</li>"
            for i in items
        )
        return f"<h3>{title} ({len(items)})</h3><ul>{rows}</ul>"

    def name_section(title: str, names: list[str]) -> str:
        if not names:
            return f"<h3>{title}</h3><p>None.</p>"
        rows = "".join(f"<li>{html.escape(n)}</li>" for n in names)
        return f"<h3>{title} ({len(names)})</h3><ul>{rows}</ul>"

    body = (
        outbox_section("Pending for more than 15 minutes", digest.stuck_pending)
        + outbox_section("Failed", digest.failed)
        + name_section("Employees with no assignment", digest.no_assignment)
        + name_section(f"Employees with no entry in the last {WORKING_DAYS_WINDOW} working days", digest.no_recent_entry)
    )
    return subject, body


async def _outbox_items(
    session_factory: async_sessionmaker[AsyncSession], now: datetime
) -> tuple[list[OutboxRow], list[OutboxRow]]:
    async with session_factory() as session:
        pending = (
            await session.execute(
                select(OutboxRow)
                .where(OutboxRow.state == OutboxState.PENDING.value, OutboxRow.created_at < now - PENDING_AGE_LIMIT)
                .order_by(OutboxRow.created_at)
            )
        ).scalars().all()
        failed = (
            await session.execute(
                select(OutboxRow).where(OutboxRow.state == OutboxState.FAILED.value).order_by(OutboxRow.created_at)
            )
        ).scalars().all()
    return list(pending), list(failed)


async def gather(
    odoo: OdooClient, session_factory: async_sessionmaker[AsyncSession], now: datetime
) -> Digest:
    pending_rows, failed_rows = await _outbox_items(session_factory, now)

    employees = await odoo.execute_kw("hr.employee", "search_read", [[("active", "=", True)]], {"fields": ["name"]})
    names = {e["id"]: e["name"] for e in employees}
    # An outbox row's employee may since have been archived; still name them.
    missing = {r.employee_id for r in pending_rows + failed_rows} - set(names)
    if missing:
        extra = await odoo.execute_kw(
            "hr.employee",
            "search_read",
            [[("id", "in", sorted(missing)), ("active", "in", [True, False])]],
            {"fields": ["name"]},
        )
        names.update({e["id"]: e["name"] for e in extra})

    def item(row: OutboxRow) -> OutboxItem:
        return OutboxItem(
            employee=names.get(row.employee_id, f"employee #{row.employee_id}"),
            entry_date=row.entry_date,
            op=row.op,
            attempts=row.attempts,
            age_minutes=int((now - row.created_at).total_seconds() // 60),
            last_error=row.last_error,
        )

    mapped = await odoo.execute_kw(
        "project.sale.line.employee.map", "search_read", [[]], {"fields": ["employee_id"]}
    )
    with_assignment = {m["employee_id"][0] for m in mapped}

    window_start = last_working_days(now.date())[-1]
    recent = await odoo.execute_kw(
        "account.analytic.line",
        "search_read",
        [[("employee_id", "in", list(names)), ("date", ">=", window_start.isoformat())]],
        {"fields": ["employee_id"]},
    )
    with_recent_entry = {r["employee_id"][0] for r in recent}

    return Digest(
        stuck_pending=[item(r) for r in pending_rows],
        failed=[item(r) for r in failed_rows],
        no_assignment=sorted(n for i, n in names.items() if i not in with_assignment),
        no_recent_entry=sorted(n for i, n in names.items() if i not in with_recent_entry),
    )


async def send(odoo: OdooClient, recipients: str, subject: str, body_html: str) -> int:
    """Queue the digest as a mail.mail; Odoo's own outgoing-mail cron delivers
    it, so 'sent' here means 'accepted by Odoo', not 'delivered'."""
    mail_id = await odoo.execute_kw(
        "mail.mail",
        "create",
        [{"subject": subject, "body_html": body_html, "email_to": recipients, "auto_delete": True}],
    )
    return mail_id[0] if isinstance(mail_id, list) else mail_id
