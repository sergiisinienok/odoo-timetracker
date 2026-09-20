# Phase 0 Gate Review

**Date:** 20 Sep 2026
**Reviewed by:** Sergii (owner) + Claude
**Environment:** `edu-timetracking.odoo.com` (Odoo 19.0+e), a free/eval trial — **not yet the real `particlesg.odoo.com` sandbox**

## The one caveat that qualifies everything below

Every fact in `odoo_profile.json` was probe-derived, exactly as ground
rule 1 requires — but derived against the trial, not the real sandbox.
Per Appendix D risk #8 ("Sandbox and production Odoo differ") and the
plan's own instruction ("assume they do until proven otherwise"), **the
full probe suite needs re-running against `particlesg.odoo.com` before
Phase 1 code is trusted against production behaviour.** Nothing here is
wrong — it's provisional. Re-running the suite is cheap now that every
probe script already exists; treat it as the actual first task once real
sandbox access exists, not a formality to skip.

## Gate checklist

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | `odoo_profile.json` complete, committed, every value from a probe | ✅ | 17 keys, all probe-derived (0.1–0.9); two intentionally null (see below) |
| 2 | Validation field named, write test recorded | ✅ | `validation_field="validated"`, `validated_line_writable/deletable=true` (0.2) |
| 3 | Unpaid recipe proven and reproducible | ✅ | Reproduced identically across two separate runs (0.5) |
| 4 | Mapping returns distinct lines for two employees, one project | ✅ | Sergii→line 1, Polina→line 2, project 2 (0.4) |
| 5 | Both billing modes through the same assignment lookup | ✅ | Third employee→line 3 (flat-rate), same mechanism (0.9) |
| 6 | Writes on behalf of other employees succeed | ✅ | 6/6 ops, zero AccessError (0.8); reconfirmed for a third employee in 0.9 |
| 7 | Assignment dates resolved to real fields, named, read back | ⚠️ resolved differently | No such field exists anywhere (0005) — owner decision: **drop enforcement**. `assignment_start_source`/`assignment_end_source` are `null` by deliberate choice, not omission |
| 8 | Every plan-contradicting probe reported and resolved | ✅ | Six decision docs (0001–0006), all resolved or explicitly forward-flagged |

## Item 7, in full

This is the one place Phase 0 didn't land where the plan expected. No
field on `sale.order.line`, `sale.order`, or
`project.sale.line.employee.map` holds an assignment's start/end date —
confirmed, not guessed (0.4, cross-checked against Planning's
`planning.slot` too, which also doesn't help without adding a second
unsynced system). Per 0.7's own text, this was explicitly the owner's
call, not something to resolve unilaterally.

**Decision: drop date enforcement.** Consequence made explicit in 0005:
the brief's "someone who joins mid-month can log from their start date
and not before" doesn't hold as written. What still stands: the picker
itself is gated by whether a mapping row exists at all, plus the daily
cap, period locking, and approver review of the whole month before
invoicing. Reversible later if the real sandbox or a Studio field
changes the calculus.

## Decisions log summary

- **0001** — Odoo 19 / trial RPC quirks: `has_group()` broken,
  `group_ids` rename, `ir.model`/`ir.model.data` access-restricted.
  Workarounds in place, reused throughout.
- **0002** — Corrects 0001's wrong empty-domain claim; documents the
  real `call()` helper convention.
- **0003** — No company-level validated-through field. Forward-flagged
  for Phase 2.1's `resolve_period_state()`.
- **0004** — `readonly_timesheet` turned out *not* user-relative here,
  contrary to the brief's stated risk. No design consequence.
- **0005** — The big one (see above).
- **0006** — `sale.order.line`'s `_at_date` fields are misleading read
  plainly; excluded from checks.

## Not on the checklist, worth knowing anyway

- **0.10 (licensing question) is sent, not yet answered.** Explicitly
  non-blocking per the plan — doesn't hold up this gate — but worth a
  follow-up once the account manager replies, recorded in
  `docs/licensing-answer.md` per the plan's own repo layout.
- **The integration user needed Project and Sales access added
  mid-Phase-0** (0.5), beyond what 0.1 originally granted. Worth
  granting all three from the start when provisioning the real
  integration user on `particlesg.odoo.com`.
- **Test data exists on the trial** (three test employees, a test
  project/order, eight role products, two pricelists) — fine to leave
  as-is; Phase 1's own test strategy (Appendix C) expects tagged,
  cleanable test fixtures of its own regardless.

## Verdict

Seven of eight checklist items pass cleanly. The eighth resolved through
an explicit, documented owner decision rather than the plan's expected
path — which is exactly what ground rule 5 is for. **Phase 0 is
complete.** Phase 1 can begin once the trial-vs-production caveat above
is either accepted as a known risk or closed by re-running the probe
suite against the real sandbox.
