"""Step 2b.7: a row queued in the old (assignment) shape survives the Alembic
migration and drains to exactly the line it always would have — project, task
left empty, and the order line the old kind implied recorded explicitly.

Downgrades the dev database one revision, inserts old-shape rows by raw SQL,
upgrades, drains. Always leaves the database at head."""

import datetime
import os
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, delete, select, text

from alembic import command
from tti.outbox.models import OutboxRow
from tti.outbox.service import attempt_row

pytestmark = pytest.mark.odoo

OLD_REVISION = "211bfd794469"  # the revision before task_id/write_billing
EMP = 1
TODAY = datetime.date.today().isoformat()
_API_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    cfg = Config(str(_API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_API_ROOT / "alembic"))
    return cfg


def _sync_url() -> str:
    return os.environ["DATABASE_URL"]


_INSERT = text(
    """
    INSERT INTO outbox (id, employee_id, op, entry_date, hours, assignment, project_id, so_line_id, note,
                        odoo_line_id, state, attempts, next_attempt)
    VALUES (:id, :emp, :op, :day, :hours, :assignment, :project_id, :so_line_id, :note,
            :odoo_line_id, 'pending', 1, now() - interval '1 minute')
    """
)


def _old_row(op, assignment, *, so_line_id, note, line=None):
    return {
        "op": op,
        "assignment": assignment,
        "project_id": 2,
        "so_line_id": so_line_id,
        "odoo_line_id": line,
        "note": note,
    }


async def _drain(session_factory, odoo_client, profile, period_service, row_id):
    async with session_factory() as session:
        row = (await session.execute(select(OutboxRow).where(OutboxRow.id == row_id).with_for_update())).scalar_one()
        await attempt_row(session, row, odoo_client, profile, period_service, reconcile_first=True)
    async with session_factory() as session:
        return await session.get(OutboxRow, row_id)


async def test_old_shape_rows_migrate_and_drain_to_the_right_lines(
    odoo_client, session_factory, profile, period_service, temp_records
):
    existing = await temp_records(
        "account.analytic.line",
        {"employee_id": EMP, "project_id": 2, "date": TODAY, "unit_amount": 1.0, "name": "2b7 migration existing",
         "so_line": False},
    )  # fmt: skip
    paid, unpaid, update = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rows = {
        paid: _old_row("create", "project:2:paid", so_line_id=1, note="2b7 migrated paid"),
        unpaid: _old_row("create", "project:2:unpaid", so_line_id=None, note="2b7 migrated unpaid"),
        update: _old_row("update", "project:2:paid", so_line_id=1, note="2b7 migrated update", line=existing),
    }

    engine = create_engine(_sync_url())
    cfg = _alembic_config()
    command.downgrade(cfg, OLD_REVISION)
    try:
        with engine.begin() as conn:
            for rid, r in rows.items():
                conn.execute(_INSERT, {"id": rid, "emp": EMP, "day": TODAY, "hours": 2.0, **r})
    finally:
        command.upgrade(cfg, "head")

    created = []
    try:
        migrated = {}
        for rid in rows:
            migrated[rid] = await _drain(session_factory, odoo_client, profile, period_service, rid)
        assert all(r.state == "synced" for r in migrated.values()), {k: v.last_error for k, v in migrated.items()}
        assert all(r.task_id is None and r.write_billing is True for r in migrated.values())

        for rid, expect_so_line in ((paid, 1), (unpaid, False)):
            line_id = migrated[rid].odoo_line_id
            created.append(line_id)
            [rec] = await odoo_client.execute_kw(
                "account.analytic.line", "read", [[line_id]], {"fields": ["so_line", "task_id", "project_id"]}
            )
            assert (rec["so_line"][0] if rec["so_line"] else False) == expect_so_line
            assert rec["task_id"] is False and rec["project_id"][0] == 2

        # The old update wrote project and so_line, and still does.
        [rec] = await odoo_client.execute_kw("account.analytic.line", "read", [[existing]], {"fields": ["so_line"]})
        assert rec["so_line"][0] == 1
    finally:
        if created:
            await odoo_client.execute_kw("account.analytic.line", "unlink", [created])
        async with session_factory() as session:
            await session.execute(delete(OutboxRow).where(OutboxRow.id.in_(list(rows))))
            await session.commit()
        engine.dispose()
