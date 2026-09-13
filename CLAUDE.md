# CLAUDE.md

Durable context for Claude Code in this repo. Full detail lives in
`docs/brief.md` (the *why*) and `docs/implementation-plan.md` (the *how*) —
read those before anything touching Odoo data modeling, billing logic, or
phase sequencing. This file is the fast-loading summary, not a replacement.

## What this is

Odoo Time Tracker: a small write-through web app that replaces employee
spreadsheets with direct Odoo timesheet entries, so client invoices bill
hours-and-materials or flat-rate engagements straight from the sales order.
Odoo is the only record — no second database, no sync job.

## Where we are

**Phase 0 — Odoo foundation.** Nothing past this phase gets built until
`odoo_profile.json` is complete and every value in it is probe-derived, not
guessed. Current status: **0.1 and 0.2 done** — `odoo_profile.json` fully
populated for both (`validation_field`, `employee_validated_through`,
`company_validated_through`, `readonly_is_user_relative`,
`validated_line_writable`/`validated_line_deletable` all confirmed). **0.3
next** (service products, both invoicing modes).

One outstanding forward-flag from 0.2, not blocking but worth knowing before
Phase 2.1: this instance has no company-level timesheet fallback field —
`company_validated_through` is `null`. See
`docs/decisions/0003-no-company-validated-through-field.md` before
implementing `resolve_period_state()`.

Current status: 0.1–0.4 done. 0.4's mapping mechanism
(project.sale.line.employee.map) confirmed working exactly as the plan
named it — two employees, two distinct order lines, same project.
Assignment validity date enforcement is DROPPED (Appendix D risk #4
materialized — no usable date field exists on sale.order.line,
sale.order, or the mapping model; see docs/decisions/0005). Consequence:
0.7 needs only the two originally-planned Studio fields
(default_project_field, app_entry_id_field) — no Studio date pair. 0.5
next (the unpaid-line recipe).

## Ground rules (non-negotiable — from `docs/implementation-plan.md`)

1. **Never assume an Odoo field name.** Confirm it via a probe against the
   live instance first.
2. **`odoo_profile.json` is the single source of truth** for Odoo facts.
   Code reads `profile.<key>`, never a hardcoded field or group name.
3. **Never write to production Odoo.** Sandbox only, integration user only,
   test project only, until Phase 3.
4. **A step is done when its validate command produces the stated output** —
   not when the code looks right.
5. **When a probe contradicts this plan, the probe wins.** Stop, write it up
   in `docs/decisions/`, ask before working around it. Don't adapt silently.
6. **No secret ever enters the repo.** `.env` is gitignored; `.env.example`
   ships with empty values.

## Environment quirks discovered so far

Full writeups belong in `docs/decisions/`; this is the quick-reference so
they don't get rediscovered every session.

- **We're currently probing against `edu-timetracking.odoo.com`, a free/eval
  trial — not yet the real `particlesg.odoo.com` sandbox.** Any Phase 0 fact
  gathered here is provisional until re-verified against the real instance.
  The trial runs a `saas_trial` RPC wrapper that has already been caught
  behaving differently from stock Odoo.
- **`res.users.has_group()` faults over XML-RPC on this trial**
  (`TypeError: missing 1 required positional argument`). Workaround: read
  `res.users.all_group_ids`, then `res.groups.read(ids,
  fields=["display_name"])` and match on the label instead of the technical
  group id. Not yet confirmed whether this is trial-specific — re-check
  against the real sandbox before relying on either approach long-term.
- **Odoo 19 field renames** vs. what older docs/training data assume:
  `res.users.group_ids` (not `groups_id`); `res.groups` has no
  `category_id` — use `display_name` (includes the category prefix, e.g.
  `"Timesheets / Administrator"`) or the `privilege_id` many2one instead.
- **When using the shared `call()` helper, pass the domain itself as the
  third argument — don't double-wrap it.** `call(model, "search_read", [],
  fields=...)` for no filter, `call(model, "search_read",
  [("field", "=", "value")], fields=...)` for one condition. An earlier
  version of this note claimed Odoo 19 rejects an empty `[]` domain
  outright — that was wrong, see
  `docs/decisions/0002-domain-argument-convention.md`.
- **`readonly_timesheet` turned out not to be user-relative here**, contrary
  to what the plan flagged as a risk — it tracked `validated` identically
  for both an approver and an ordinary employee. Doesn't change anything
  (the app was already designed to not rely on it), but don't assume this
  holds on the real sandbox without re-checking. See
  `docs/decisions/0004-readonly-timesheet-not-user-relative.md`.
- **Validated lines are writable and deletable over the API** — confirmed by
  direct test, not assumed. Matches the plan's own expectation: stock Odoo's
  validation is not enforcement, so the app has to be.

## Repo layout

(from `docs/implementation-plan.md`'s own structure — not fully scaffolded
yet as of Phase 0)

```
docs/               brief.md, implementation-plan.md, decisions/, licensing-answer.md
tools/              probe + spike scripts, run by hand against the live sandbox
odoo_profile.json   generated by probes, committed — never hand-edit
api/                FastAPI backend (Phase 1+)
web/                React frontend (Phase 1+)
```

**Script naming convention in `tools/`:** scripts the plan itself names by
exact filename in its own "Validate" command text — `spike_odoo_timesheet_lock.py`,
`probe_assignments.py`, `probe_unpaid_line.py`, `probe_studio_fields.py`,
`probe_products.py`, `probe_internal_project.py`, `probe_flat_rate.py`,
`probe_write_other_employee.py`, `build_profile.py` — keep those exact
names, so the repo stays in sync with what `docs/implementation-plan.md`
literally says to run. Everything else — ad-hoc scripts written to get
through a specific step but not named by the plan — gets prefixed
`p{phase}s{step:02d}-`, e.g. `p0s02-probe_create_test_lines.py` for a
phase-0-step-2 helper.

## Running things right now (Phase 0)

```bash
# integration user's spike — reads groups, validation fields, sample lines
python3 tools/spike_odoo_timesheet_lock.py

# step 0.2 support scripts (ad-hoc, not named by the plan itself)
python3 tools/p0s02-probe_odoo_version.py                        # exact Odoo version string
python3 tools/p0s02-probe_create_test_lines.py <employee email>  # creates two test timesheet lines
python3 tools/p0s02-probe_validated_line_lock.py <line id>       # write/unlink test on a validated line — destructive, run last
```

Run scripts without `| head` until you've confirmed every section still
completes cleanly — Odoo 19 has already broken a mid-script assumption once
without erroring loudly until that point in the output.

## Commit hygiene

`.env` must never be staged. If a tool (Codacy, an IDE plugin, etc.) drops
config into the repo root uninvited, decide deliberately whether it should
be tracked or gitignored — don't let it ride along on an unrelated commit.