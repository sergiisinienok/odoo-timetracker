# Phase 2 Gate Review

**Date:** 24 Sep 2026
**Status:** ACCEPTED by the owner, 24 Sep 2026 — with the caveats named below
**Prepared by:** Claude, from the evidence in the commits named below; reviewed and accepted by Sergii (owner)
**Environment:** `edu-timetracking.odoo.com` (Odoo 19.0+e), a free/eval trial — **still not the real `particlesg.odoo.com` sandbox**

## The one caveat that qualifies everything below

Same caveat as the Phase 0 and Phase 1 gate reviews, now covering the whole
product: every step in Phase 2 was built and proven against the trial, not the
real sandbox. Nothing here is wrong — it is provisional. Re-running the Phase 0
probe suite against `particlesg.odoo.com` and re-verifying Phase 2's behaviour
there (in particular the `mail.mail` grant, decision 0009) is still the first
task of Phase 3.

## Gate checklist

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Domain rules at 100% unit coverage, network disabled | ✅ | `pytest tests/unit --cov=tti.domain --cov-branch --cov-fail-under=100` → 46 statements, 10 branches, 0 missed. Network-off is enforced, not assumed: `tests/unit/conftest.py` makes any socket connect or name lookup raise, and `test_network_disabled.py` proves the block works |
| 2 | App-enforced period locking, demonstrated independently of Odoo's behaviour | ✅ after a fix | `test_app_refuses_writes_that_odoo_itself_would_accept`: in a locked month the app refuses create/update/delete while the same three writes made straight to Odoo succeed. **Testing this found a hole** (see gap 1 below): queued writes ignored the lock at drain time. Fixed in `cdab6e3` |
| 3 | Outage test: input survives, queue drains, exactly one line per entry | ✅ after a fix | `test_input_survives_an_outage_and_drains_to_exactly_one_line_each`: a working client switched to unavailable after the caches are warm; 3 entries accepted as pending, queue drains, exactly one Odoo line each. **It failed before the fix** (gap 2): an outage refused new entries. Fixed in `949cb50` |
| 4 | Uncertain-outcome test passes 20 consecutive runs | ✅ | The whole test run 20 separate times, stopping at the first failure: 20 of 20 passed, ~29 s each. Each run is itself 20 write-lose-response-reconcile cycles, so ~400 cycles, exactly one Odoo line every time. Leftovers afterwards: none |
| 5 | App view and Odoo line list reconcile exactly for a full month | ✅ | `test_app_view_reconciles_with_odoo_for_a_full_month`: August 2026, every working day plus both month edges, all assignment kinds, three edits and two deletes. Same line ids; same date, hours, note and project per line; per-day and month totals equal |
| 6 | No rate or amount in any response body | ✅ | Playwright `no API response body carries a rate, amount, or currency field` (step 2.5), still green after step 2.8 and the gap fixes. The audit log and the digest carry none either |
| 7 | Backup restored successfully in a drill | ✅ with a caveat | `docs/restore-drill.md`: 3 seeded outbox rows dumped and restored into a scratch database, same row count, same checksum, same Alembic version. **Caveat:** the nightly 02:00 UTC schedule and 14-day pruning have never been observed running unattended — only manual dumps |
| 8 | Key rotation rehearsed | ✅ for the Odoo key | `docs/key-rotation.md`: new key created, containers recreated and verified to hold it, old key deleted, then re-verified with authenticated calls from inside both containers. `SESSION_SECRET`, `GOOGLE_CLIENT_SECRET` and `POSTGRES_PASSWORD` are documented but **not rehearsed** |

## What testing the gate found (decision 0010)

The gate's outage and locking items had only been covered by tests that faked
the failure at the write call, or seeded a row straight into Postgres. Tests
that break Odoo the way an outage does found three real defects, all fixed in
their own commits:

1. **Queued writes drained into a locked month** (`cdab6e3`). The period was
   checked once, at save time. Odoo accepts writes into a validated month, so a
   row queued during an outage was written whenever it next succeeded — after
   an approver had closed the month. Now every write attempt re-reads the lock
   fresh; a locked month fails the row with `period_locked`. A create that
   reached Odoo before the lock is still reconciled to `synced`.
2. **An outage refused new entries** (`949cb50`). `create_entry` reads
   assignments, period state and the day's hours from Odoo before enqueueing, so
   with Odoo down the employee got a 503 and their input was lost. Now those
   fall back to the last-known value (up to 24 h) while Odoo is unreachable;
   the drain-time lock check never does.
3. **A retry while Odoo was still down escaped the worker** (`cd3b15c`). The
   reconcile search before a retry sat outside the error handling; it raised,
   the transaction rolled back, and the row was retried every 10 s with an
   ERROR log and no backoff. Found by accident while testing gap 1.

## Item 5 of Phase 1, closed

Phase 1's gate accepted `OdooUncertain` as untested and deferred it to Phase 2.
It is now exercised end to end: a proxy eats the response after the write
lands, the client sees `OdooUncertain`, the row stays pending, and the worker's
reconcile-before-create finds the existing line — 20 runs of 20 cycles, one
line every time.

## Decisions log since Phase 1

- **0008** — quick-add placement (step 2.5).
- **0009** — the integration user had no access to `mail.mail`; a group with
  read + create only was granted on the trial (probe: read True, create True,
  write False, unlink False). **Must be repeated on the real sandbox and on
  production.**
- **0010** — the three gaps above, with the known limits of the outage fix.

## Not on the checklist, worth knowing anyway

- **Known limits of the outage fix.** Editing or deleting an *existing* entry
  during an outage still refuses (the ownership check reads the line from Odoo);
  only new entries are covered. Another writer can push an employee over the
  daily cap during an outage. The last-known caches live in the api process, so
  a restart mid-outage starts cold and refuses (with a plain 503 message).
- **`/readyz` cannot detect a dead Odoo key** — its Odoo check is the
  unauthenticated `version` call. Deferred by the owner at step 2.8.
- **The daily digest arrived.** Queued in Odoo as `mail.mail` #18 addressed to
  the owner, and confirmed received by the owner. That covers the full path:
  `mail.mail` grant (0009) → Odoo's outgoing-mail cron → delivery. The
  worker's *scheduled* daily send (07:00 UTC) has not yet been observed; this
  email came from a manual `python -m tti.ops` run.
- **Step 2.8 choices that are Claude's, not the plan's:** the rate limits
  (120/min per session, 30/min for mutations, 30/min per address unauthenticated),
  the in-memory per-process limiter, and best-effort `audit_log` writes.
  Unauthenticated mutation attempts are not audited (no employee to attribute
  them to).
- **The Origin check needs `PUBLIC_BASE_URL` to match the browser's origin
  exactly.** In production it must be the real HTTPS URL or every write gets
  403.
- **One unexplained Playwright failure.** During step 2.8 the history spec
  failed once (the month filter) while Odoo returned a 429 to the test's own
  seeding; it passed alone and on a full rerun. The cause was not confirmed.
- **Test hygiene.** The browser suite removes its Odoo lines but leaves two
  synced rows in the local outbox each run. Cleaned by hand during this
  review; the tests themselves were not changed.
- **Not done and not claimed:** the Phase 2 gate does not include the phone
  browser on a real domain, the `PeriodService` 5-minute cache invalidation hook
  (CLAUDE.md quirk), or auto-migration on container start (run
  `alembic upgrade head` by hand, including for `audit_log`).

## Verdict

All eight checklist items are met, two of them only after real defects found
by the gate's own tests were fixed. Two carry stated caveats (unobserved
nightly backup; only the Odoo key rehearsed). **The owner accepted those
caveats. Phase 2 is complete.** Phase 3 (pilot) begins with re-running the
probe suite against the real sandbox.

**Owner's decision on the caveats:** accepted. Both stay open as things to
observe rather than fix: the first nightly backup dump appearing on its own,
and the worker's first scheduled 07:00 UTC digest arriving.
