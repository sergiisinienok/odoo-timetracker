"""Step 2.3's own test list, using a proxy that can be made to fail (see
proxy.py):

  - Odoo unreachable at save -> pending, nothing lost; Odoo returns ->
    the worker syncs; exactly one line exists in Odoo.
  - The uncertain case: the connection dies after the request is sent but
    before the response. Assert exactly one line in Odoo. This is the
    test the whole idempotency design exists for.
  - A rejected write goes failed and is never retried.
  - Two workers running concurrently do not double-process a row.

All of these hit the live sandbox for real — the proxy forwards to it,
it isn't mocked.
"""

from __future__ import annotations

import asyncio
import datetime
import socket
from decimal import Decimal

import pytest
from proxy import FaultProxy
from sqlalchemy import delete

from tti.odoo.client import OdooClient
from tti.outbox.models import OutboxRow, OutboxState
from tti.outbox.service import OutboxService
from tti.outbox.worker import process_one_pending_row

pytestmark = pytest.mark.odoo

TM_EMPLOYEE_ID = 1
TODAY = datetime.date.today()


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
async def clean_outbox_table(session_factory):
    """These tests assert on the *whole* queue's behavior (SKIP LOCKED
    contention, dequeue ordering) — a stray row left by an unrelated test
    would silently change what gets picked up. Every entry-creating test
    elsewhere is responsible for deleting its own outbox row; this is a
    belt-and-suspenders guarantee specifically for this file."""
    async with session_factory() as session:
        await session.execute(delete(OutboxRow))
        await session.commit()
    yield


@pytest.fixture
async def unreachable_odoo_client():
    port = _unused_port()
    async with OdooClient(url=f"http://127.0.0.1:{port}", db="x", user="x", api_key="x", timeout=3.0) as client:
        yield client


@pytest.fixture
async def proxy():
    import os

    p = FaultProxy(upstream_url=os.environ["ODOO_URL"])
    await p.start()
    try:
        yield p
    finally:
        await p.stop()


@pytest.fixture
async def proxied_odoo_client(proxy):
    import os

    async with OdooClient(
        url=proxy.url, db=os.environ["ODOO_DB"], user=os.environ["ODOO_USER"], api_key=os.environ["ODOO_KEY"]
    ) as client:
        yield client


async def _find_by_app_entry_id(odoo_client, profile, outbox_id) -> list[int]:
    rows = await odoo_client.execute_kw(
        "account.analytic.line",
        "search_read",
        [[(profile.app_entry_id_field, "=", str(outbox_id))]],
        {"fields": ["id"]},
    )
    return [r["id"] for r in rows]


async def _cleanup(odoo_client, session_factory, outbox_id, line_ids):
    if line_ids:
        await odoo_client.execute_kw("account.analytic.line", "unlink", [line_ids])
    async with session_factory() as session:
        await session.execute(delete(OutboxRow).where(OutboxRow.id == outbox_id))
        await session.commit()


async def _force_due(session_factory, outbox_id) -> None:
    """Skip the backoff wait in tests. A comfortable margin in the past,
    not exactly now() — the DB server (in the Podman VM) and this test
    process's clocks agree to within a network round trip, not to the
    microsecond, and next_attempt <= now() is a strict comparison."""
    async with session_factory() as session:
        row = await session.get(OutboxRow, outbox_id)
        row.next_attempt = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=5)
        await session.commit()


async def test_unreachable_at_save_then_worker_syncs_once_odoo_returns(
    session_factory, odoo_client, unreachable_odoo_client, period_service, profile
):
    outbox = OutboxService(session_factory, unreachable_odoo_client, profile, period_service)
    result = await outbox.enqueue_create(
        employee_id=TM_EMPLOYEE_ID,
        entry_date=TODAY,
        hours=Decimal("1.0"),
        project_id=1,
        task_id=None,
        so_line_id=None,
        note="2.3 outbox test: unreachable",
    )
    assert result.state == OutboxState.PENDING

    # Nothing was lost: it's really in the queue.
    async with session_factory() as session:
        row = await session.get(OutboxRow, result.outbox_id)
        assert row.state == OutboxState.PENDING.value
        assert row.attempts == 1

    # And nothing exists in Odoo yet.
    assert await _find_by_app_entry_id(odoo_client, profile, result.outbox_id) == []

    try:
        # "Odoo returns" — the worker retries with a real, working client.
        await _force_due(session_factory, result.outbox_id)
        found = await process_one_pending_row(session_factory, odoo_client, profile, period_service)
        assert found is True

        async with session_factory() as session:
            row = await session.get(OutboxRow, result.outbox_id)
            assert row.state == OutboxState.SYNCED.value
            assert row.odoo_line_id is not None

        line_ids = await _find_by_app_entry_id(odoo_client, profile, result.outbox_id)
        assert len(line_ids) == 1
    finally:
        line_ids = await _find_by_app_entry_id(odoo_client, profile, result.outbox_id)
        await _cleanup(odoo_client, session_factory, result.outbox_id, line_ids)


async def test_uncertain_write_produces_exactly_one_line(session_factory, odoo_client, proxy, profile, period_service):
    """The test the whole idempotency design exists for — run repeatedly,
    not just once, per the plan's own "Done when" (20 consecutive runs)."""
    import os

    for i in range(20):
        proxied_client = OdooClient(
            url=proxy.url, db=os.environ["ODOO_DB"], user=os.environ["ODOO_USER"], api_key=os.environ["ODOO_KEY"]
        )
        outbox_on_proxy = OutboxService(session_factory, proxied_client, profile, period_service)
        try:
            # Authenticate through the proxy *before* arming the eaten
            # response — execute_kw lazily authenticates on first use, and
            # if that's the call whose response gets eaten, the create
            # itself never even gets attempted.
            await proxied_client.authenticate()
            proxy.eat_next_n_responses = 1
            result = await outbox_on_proxy.enqueue_create(
                employee_id=TM_EMPLOYEE_ID,
                entry_date=TODAY,
                hours=Decimal("1.0"),
                project_id=1,
                task_id=None,
                so_line_id=None,
                note=f"2.3 outbox test: uncertain run {i}",
            )
        finally:
            await proxied_client.aclose()

        try:
            # The write genuinely happened — Odoo has the line already,
            # even though our client saw it as uncertain (pending).
            assert result.state == OutboxState.PENDING
            line_ids = await _find_by_app_entry_id(odoo_client, profile, result.outbox_id)
            assert len(line_ids) == 1, f"run {i}: expected exactly 1 line after the uncertain write, got {line_ids}"

            # The worker retries with a normal client — reconcile-before-create
            # must find the existing line rather than creating a second one.
            await _force_due(session_factory, result.outbox_id)
            found = await process_one_pending_row(session_factory, odoo_client, profile, period_service)
            assert found is True

            async with session_factory() as session:
                row = await session.get(OutboxRow, result.outbox_id)
                assert row.state == OutboxState.SYNCED.value
                assert row.odoo_line_id == line_ids[0]

            line_ids_after = await _find_by_app_entry_id(odoo_client, profile, result.outbox_id)
            assert len(line_ids_after) == 1, f"run {i}: expected exactly 1 line after reconcile, got {line_ids_after}"
        finally:
            line_ids = await _find_by_app_entry_id(odoo_client, profile, result.outbox_id)
            await _cleanup(odoo_client, session_factory, result.outbox_id, line_ids)


async def test_rejected_write_goes_failed_and_is_never_retried(session_factory, odoo_client, period_service, profile):
    outbox = OutboxService(session_factory, odoo_client, profile, period_service)
    # project_id 999999 doesn't exist -> Odoo rejects the create with a
    # UserError -> OdooRejected.
    result = await outbox.enqueue_create(
        employee_id=TM_EMPLOYEE_ID,
        entry_date=TODAY,
        hours=Decimal("1.0"),
        project_id=999999,
        task_id=None,
        so_line_id=None,
        note="2.3 outbox test: rejected",
    )
    try:
        assert result.state == OutboxState.FAILED
        assert result.last_error

        async with session_factory() as session:
            row = await session.get(OutboxRow, result.outbox_id)
            attempts_before = row.attempts
            assert row.state == OutboxState.FAILED.value

        # The worker's dequeue query only selects state='pending' — a
        # failed row is structurally never picked up.
        await _force_due(session_factory, result.outbox_id)
        found = await process_one_pending_row(session_factory, odoo_client, profile, period_service)
        assert found is False

        async with session_factory() as session:
            row = await session.get(OutboxRow, result.outbox_id)
            assert row.state == OutboxState.FAILED.value
            assert row.attempts == attempts_before  # untouched

        assert await _find_by_app_entry_id(odoo_client, profile, result.outbox_id) == []
    finally:
        await _cleanup(odoo_client, session_factory, result.outbox_id, [])


async def test_two_workers_do_not_double_process_a_row(session_factory, odoo_client, period_service, profile):
    from uuid import uuid4

    outbox_id = uuid4()
    async with session_factory() as session:
        row = OutboxRow(
            id=outbox_id,
            employee_id=TM_EMPLOYEE_ID,
            op="create",
            entry_date=TODAY,
            hours=Decimal("1.0"),
            project_id=1,
            so_line_id=None,
            note="2.3 outbox test: concurrent workers",
            state=OutboxState.PENDING.value,
            attempts=0,
            # Explicit, comfortably in the past — not the next_attempt=now()
            # server default, which races against this test process's own
            # now() moments later. See _force_due's comment.
            next_attempt=datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=5),
        )
        session.add(row)
        await session.commit()

    try:
        results = await asyncio.gather(
            process_one_pending_row(session_factory, odoo_client, profile, period_service),
            process_one_pending_row(session_factory, odoo_client, profile, period_service),
        )
        # Exactly one of the two concurrent calls found and processed the
        # row; SKIP LOCKED made the other one see nothing due.
        assert sorted(results) == [False, True]

        line_ids = await _find_by_app_entry_id(odoo_client, profile, outbox_id)
        assert len(line_ids) == 1

        async with session_factory() as session:
            row = await session.get(OutboxRow, outbox_id)
            assert row.state == OutboxState.SYNCED.value
            assert row.attempts == 1  # only one of the two calls actually attempted it
    finally:
        line_ids = await _find_by_app_entry_id(odoo_client, profile, outbox_id)
        await _cleanup(odoo_client, session_factory, outbox_id, line_ids)
