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

Current status: **Phase 0 complete** — gate reviewed and passed (7/8
clean, item 7 — assignment dates — resolved by explicit owner decision:
enforcement dropped, see decisions/0005). Full gate review:
docs/phase-0-gate-review.md.

**Before trusting any of this against production:** everything was
probed against the trial (edu-timetracking.odoo.com), not
particlesg.odoo.com. Re-run the full probe suite against the real
sandbox first — every script already exists in tools/, this is
re-running them, not rebuilding them.

Next: Phase 1 (walking skeleton) — 1.1, scaffold and compose.

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
- **The integration user needs Project and Sales access, not just Timesheets.** -
  0.1 only granted Timesheets Administrator; reading
  sale.order.line directly (first needed in 0.5) requires Project and/or
  Sales access too — both were still "No." Worth remembering when
  provisioning the real integration user on particlesg.odoo.com: grant
  all three from the start, not just Timesheets. Avoid "Sales/User: Own
  Documents Only" specifically — it scopes to orders where this user is
  the salesperson, which is wrong for a service account reading every
  client's orders.
- **Trial API keys can expire independently of the account itself.**
  ssinenok@gmail.com's original key from 0.1 stopped authenticating
  (XML-RPC Fault 3, bare "Access Denied" — distinct from the detailed
  Fault 4 permission errors seen elsewhere in this project) partway
  through 0.7, despite the login and account working fine. Regenerating
  it in Preferences → Account Security fixed it immediately. A script
  that worked before now failing with a bare Fault 3, credentials
  otherwise populated correctly, means check the key first.
- **`x_studio_timetracking_app_entry_id`'s Indexed flag can't be
  independently verified via the API** — `ir.model.fields` likely shares
  the same Access Rights restriction as ir.model/ir.model.data (0001).
  Set via Technical Settings, UI-confirmed only. Revisit before Phase 3
  (or when data volume actually matters) to confirm the real Postgres
  index exists, not just the metadata flag.
- **`sale.order.line`'s `_at_date`-suffixed fields (amount_to_invoice_at_date,
  qty_invoiced_at_date, etc.) are misleading when read plainly** — they
  appear to need a specific date passed via the read context, and
  without it can compute values that don't match the real invoicing
  fields at all (0006). Don't use them for anything factual; stick to
  the properly `monetary`-typed fields.

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