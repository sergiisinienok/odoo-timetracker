# 0010 — Two gaps found testing the Phase 2 gate

Status: gap 1 fixed (owner chose option 1); gap 2 and gap 3 open — found 2026-09-24 by
`api/tests/odoo/test_phase2_gate.py`.

The gate items "app-enforced period locking, demonstrated independently of
Odoo's behaviour" and "outage test: input survives, queue drains, exactly one
line per entry" were only covered by tests that faked the failure at the
write call. Tests that break Odoo the way an outage does (a working client
switched to `OdooUnavailable` after the caches are warm) show two gaps.

## What passes

- `test_app_refuses_writes_that_odoo_itself_would_accept` — with a month locked,
  the app refuses create/update/delete while the same three writes made
  straight to Odoo succeed. The lock is the app's, not Odoo's.
- `test_app_view_reconciles_with_odoo_for_a_full_month` — a full calendar month
  (every working day plus both month edges, all assignment kinds, three edits,
  two deletes): same line ids, and per line the same date, hours, note and
  project; per-day and month totals equal.

## Gap 1 — a queued write drains into a month that locked in the meantime

Fixed: option 1, `_period_open_for_write` in `outbox/service.py`.

`test_queued_write_is_not_applied_once_its_month_is_locked` fails:
"the worker wrote [932] into a locked month (row state: synced)".

`outbox/service.py` `attempt_row` never calls `PeriodService.guard()`. The
period check happens once, when the entry is accepted. A row queued during an
outage, or waiting out a backoff, is written to Odoo whenever it next
succeeds, and Odoo accepts it (`validated_line_writable` is true — the app is
the only guard, implementation plan line 169). An approver can validate a
month and hours then appear in it afterwards.

Options:

1. **Guard at drain (recommended).** Before any write attempt that would
   change Odoo, re-check the period; if locked, mark the row `failed` with
   `period_locked`, so it shows in the digest and to the employee. A create
   that reconcile finds already in Odoo stays `synced` (it was written before
   the lock). Cost: an employee's queued hours can be refused after an
   approver locks the month — which is what a lock means.
2. Accept it: queued rows always sync. Then a locked month can still change.

## Gap 2 — an outage refuses the entry instead of queueing it

`test_input_survives_an_outage_and_drains_to_exactly_one_line_each` fails with
`OdooUnavailable` raised from `entries/service.py:296` (`_existing_hours`),
before anything is enqueued.

`create_entry` makes three Odoo reads before it reaches the outbox: the
assignment list (60 s cache), the period guard (5 min cache), and the day's
existing hours for the daily cap (never cached). With Odoo down, the hours read
always fails, and once those short caches expire the other two do as well.
`main.py`'s `OdooError` handler turns that into a 503, so the employee's input
is not saved. The existing outage tests and the Playwright one never hit this:
they fail only the write call, or seed a pending row directly.

Options:

1. **Serve last-known values when Odoo is unavailable (recommended).**
   Assignments, validated-through date and the day's Odoo hours fall back to
   the last successful read (with a generous ceiling, e.g. 24 h); the cap then
   counts last-known Odoo hours plus pending rows. With no last-known value
   (cold cache) the entry is still refused, with a clear "can't check your
   limit right now" message. Gap 1's fix is what makes the stale period
   value safe: the lock is re-checked at drain.
   Weakness: the cap can be exceeded if someone else adds lines for the
   employee during the outage.
2. Accept 503 during outages, and have the UI keep the unsent form. Contradicts
   the gate's "input survives".
3. Queue without any pre-checks and validate at drain. Largest change, and
   moves refusals from save time to some later time the employee won't see.

## Not covered by either fix

Gap 2's option 1 relies on caches the api process holds in memory, so a restart
during an outage loses them (cold cache: refuse, per above).

## Gap 3 — a retry while Odoo is still down escapes the worker's error handling

Found 2026-09-24 while testing the fix for gap 1; not fixed, not part of gap 1 or 2.

`_attempt_create` and `_attempt_delete` in `outbox/service.py` run their
reconcile search (`reconcile_first`, any row with `attempts > 0`) outside the
`try` that maps `OdooUnavailable`/`OdooUncertain`/`OdooRejected`. With Odoo
still down, the search raises out of `attempt_row`; `run_worker_loop` catches it
with `logger.exception`, and the row's transaction rolls back, so `attempts`
and `next_attempt` never advance.

Effect: during a long outage a row that has already failed once is retried on
every 10 s poll with no backoff, each time logging an ERROR, and it is picked
first each time. It recovers when Odoo returns and nothing is lost. If the
reconcile search were instead *rejected* by Odoo (not unavailable), the same row
would be re-picked forever and block the queue behind it.

Fix (small): wrap the reconcile searches with the same three-way handling as
the writes below them — unavailable/uncertain → `_mark_pending_retry`,
rejected → `_mark_failed`.
