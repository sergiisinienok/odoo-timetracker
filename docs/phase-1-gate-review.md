# Phase 1 Gate Review

**Date:** 21 Sep 2026
**Reviewed by:** Sergii (owner) + Claude
**Environment:** `edu-timetracking.odoo.com` (Odoo 19.0+e), a free/eval trial — **still not the real `particlesg.odoo.com` sandbox**

## The one caveat that qualifies everything below

Same caveat as Phase 0's gate review, now covering a full working
application instead of just probe facts: every step in Phase 1 was built
and proven against the trial, not the real sandbox. Nothing here is
wrong — it's provisional. Re-running the Phase 0 probe suite against
`particlesg.odoo.com`, and re-verifying Phase 1's own behaviour there,
is still the actual first task once real sandbox access exists.

## Gate checklist

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | One real employee signed in with Google and logged one real hour | ✅ | Step 1.3: real `@particlesglobal.com` sign-in confirmed by hand. Step 1.6: full round trip through the real browser UI (sign in → add entry → see it listed), confirmed by the owner |
| 2 | That hour is a correct timesheet line in Odoo | ✅ | Step 1.5 by-hand: opened Odoo UI, confirmed date/employee/project/description/order line on an API-created line |
| 3 | Assignments come from Odoo configuration, with nothing hardcoded | ✅ | Step 1.4: built entirely from `project.sale.line.employee.map` + `hr.employee`'s Studio default field, read via `profile.default_project_field`. Live-tested: adding a mapping makes a new assignment appear with no app change |
| 4 | Unpaid entries stay unpaid after a subsequent write | ✅ | Step 1.5: `test_unpaid_entry_stays_unpaid_after_a_subsequent_unrelated_write`, passed live |
| 5 | The Odoo error taxonomy distinguishes retryable from rejected | ⚠️ accepted, deferred | `OdooUnavailable` and `OdooRejected` both proven live (step 1.2). `OdooUncertain` — the third category, the one the outbox's reconcile-not-blind-retry logic depends on — is implemented and reviewed by inspection, but never actually exercised by a test. Owner decision: accept as a known gap, close it in Phase 2 |

## Item 5, in full

`OdooUncertain` maps from `httpx.ReadTimeout`/`RemoteProtocolError` — the
request reached Odoo but the response never came back, so the outcome is
genuinely unknown. Proving this live means provoking a real
read-timeout-after-send, which needs something that accepts a connection
and stalls the response (a local mock server, not the live sandbox) —
meaningfully more test infrastructure than the other three taxonomy
cases needed. Since `OdooUncertain`'s only consumer is the reconcile
path, and the reconciler doesn't exist until Phase 2's outbox is built,
testing it in isolation now would be exercising a code path with no real
caller yet.

**Decision: accept and defer.** Close this when Phase 2 builds the
outbox/reconciler — that's also the point where `OdooUncertain` gets a
real caller to test against, rather than a synthetic one.

## Decisions log since Phase 0

- **0007** — `GOOGLE_HOSTED_DOMAIN` corrected from the plan's guessed
  `particles.global` to `particlesglobal.com`, matching every real
  `hr.employee.work_email` in the trial and the marketing site fetched
  for Appendix F. Confirmed with the owner before writing the `hd` check.

## Not on the checklist, worth knowing anyway

- **The daily cap (`DAILY_HOUR_CAP`) is not enforced yet — by design, not
  a gap.** The plan places it at step 2.1, after the checklist above, and
  explicitly requires it to count pending outbox rows too (Appendix D:
  "If pending writes are excluded from the daily total, an employee can
  exceed the cap during an outage"), which doesn't exist until Phase 2.
  Confirmed live: a 77-hour entry was accepted without complaint —
  expected at this stage, not a bug.
- **Step 1.6's own "Done when" names a phone browser on the real
  domain** — no public domain exists yet (that's Phase 3 deployment).
  Agreed explicitly with the owner to defer that specific check; the
  round trip itself was fully verified on `http://localhost`.
- **Stray test data found and cleaned during this gate review**: one
  orphaned `project.project` row ("TEMP second project for assignment
  probe", id 3) left behind by an early debugging script that crashed
  before reaching its own cleanup (see CLAUDE.md's `create()`
  XML-RPC-list-return quirk) — unlinked, no mapping rows existed on it.
  Two real manual-test timesheet lines (4h and 77h, both from by-hand
  verification during this session) — unlinked at the owner's request.
  Every dynamically-created pytest fixture across steps 1.1–1.6 already
  cleans up after itself in a `finally` block; this was the one gap, now
  closed.
- **Test data predating this session** (three test employees, the test
  project/order, role products, pricelists from Phase 0) is untouched —
  expected to persist as ongoing test fixtures, not cleaned up.

## Verdict

Four of five checklist items pass cleanly; the fifth resolved through an
explicit, documented owner decision to accept and defer, same pattern as
Phase 0's item 7. **Phase 1 is complete.** Phase 2 begins at step 2.1
(domain rules as pure functions), which also closes the `OdooUncertain`
gap above as a side effect of building the outbox it exists for.
