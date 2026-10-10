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

Current status: **Phase 2 complete** — gate reviewed and accepted, 8/8
items met (two only after fixing real defects the gate's own tests found;
two accepted with stated caveats: the nightly backup has not yet been
observed running unattended, and only the Odoo key's rotation was
rehearsed; the worker's scheduled 07:00 UTC digest is also still to be
observed). Full gate review: docs/phase-2-gate-review.md.
Earlier gates: docs/phase-1-gate-review.md, docs/phase-0-gate-review.md.

**Before trusting any of this against production:** everything was
probed and built against the trial (edu-timetracking.odoo.com), not
particlesg.odoo.com. Re-run the full probe suite against the real
sandbox first — every script already exists in tools/, this is
re-running them, not rebuilding them.

Next: Phase 2b — Tasks and billability (inserted before the pilot, decision
0011). 2b.1 (decision record and brief v8), 2b.3 (task probe) and 2b.4 (sample tasks) and 2b.5 (billing rule) are done;
2b.2 (re-running the Phase 0 probe suite against the real
`particlesg.odoo.com` sandbox) is **deliberately deferred** — the owner chose
to build 2b against the trial's `.env`, so 2b.3's facts, including the Studio
field `x_studio_billable` and the `is_so_line_edited` hand test, must be
re-confirmed on particlesg (decision 0013) before the pilot.

### Current status

- Phase: 2b — Tasks and billability (Phase 2 gate passed)
- Last completed step: 2b.5 — `resolve_billing` (2b.4 sample tasks on the trial; 2b.2 skipped for now; `INTERNAL_PROJECT_ID=33` in the local `.env`, not 1)
- Next step: 2b.6 — the catalog, read live from Odoo (`GET /api/catalog`)
- Last commit: this commit (`git log -1` — amending to embed a literal hash
  here just changes the hash, so this field names the step instead)

## Git workflow for the implementation plan

- One commit per plan step (1.1, 1.2, ... 1.6), never a partial step.
- After running a step's Validate command, show me the actual output and
  stop. Wait for my explicit go-ahead before committing — do not commit on
  your own judgment that it passed, even if the output looks clean.
- The commit body must contain the evidence: the Validate command and its
  actual output, not just a claim that it was run.
- Commit message: `Step 1.3: Google sign-in and employee resolution`
  (step number + the step's Goal line, verbatim from the plan).
- After I confirm a step, update the "Current status" block above (last
  completed step, next step, last commit hash) as part of that same commit —
  never a separate one. Status and evidence move together or not at all.
- If validation surfaces a contradiction with the plan (ground rule 5), stop
  before asking me to confirm anything. Write it under docs/decisions/ first,
  then bring both the contradiction and the step to me together.
- Never amend or squash an earlier step's commit to absorb a later fix; a fix
  is a new commit, same confirm-then-commit-with-evidence rule, that says
  which step it corrects.

Commit body shape:

    Step 1.3: A signed-in employee is an hr.employee id, or they are not signed in.

    Validate:
      pytest api/tests/unit/test_auth.py api/tests/odoo/test_employee_resolution.py -v

    Output:
      <actual passing output, pasted>

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
- **`create()` over XML-RPC on this trial can return a list (`[3]`) instead
  of a plain int**, seen on `project.project` (step 1.4) — passing that
  straight into a following `read()`/`unlink()` call crashes deep in
  Odoo's ORM (`TypeError: unhashable type: 'list'`), because it becomes a
  list-of-a-list of ids. Confirmed this is XML-RPC-specific: the same
  `create()` call over **JSON-RPC** — what the real app uses via
  `OdooClient` — returns a plain int, both for `hr.employee` and
  `project.project`. Only matters for throwaway `tools/` probe scripts
  written with `xmlrpc.client`; doesn't affect app code. If a probe's
  `create()` result looks wrong, check whether it's already a list before
  re-wrapping it.
- **`project.project.partner_id` gets silently reset to `False` if written
  *before* a `project.sale.line.employee.map` row exists on that project**,
  even though the write reads back correctly right after — reproducible,
  undiagnosed (step 1.4, building a second-project-same-customer test
  fixture). Write it *after* creating the mapping row instead and it
  sticks reliably. Only matters for test fixtures that build a project
  from scratch via the API; real projects are created through the UI
  (sales order confirmation), which evidently doesn't hit this ordering.
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
- **`PeriodService`'s 5-minute in-memory cache (step 2.2) makes manual
  verification of lock/unlock state misleading if you don't restart `api`
  between writes.** Setting `last_validated_timesheet_date` (via Odoo UI or
  API), checking the app, then clearing it back again — all within the
  same 5 minutes, without a restart — leaves the running `api` process
  showing whichever state it cached first, for up to 5 minutes after the
  real Odoo value has already changed. Bit both an automated Playwright
  run and a manual by-hand check this way (step 2.5). `docker compose
  restart api` + poll `/api/healthz` forces a cold read; there's no
  softer invalidation hook yet.

- **The integration user needs a `mail.mail` grant for the daily digest**
  (step 2.7). Stock provisioning gives it no access. Probe result: read + create
  only (write and unlink stay denied) — see `docs/decisions/0009-integration-user-cannot-use-mail-mail.md`.
  Repeat on the real sandbox and production.
- **`/readyz` cannot detect a dead Odoo key** — its Odoo check is the
  unauthenticated `version` call. After rotating `ODOO_KEY`, confirm the
  containers hold the new one (hash compare, `docs/key-rotation.md` step 4)
  and make an authenticated call; don't trust readiness alone.
- **Every Bash call in this repo needs `unset POSTGRES_PASSWORD DATABASE_URL`
  before `docker compose`** — each call is a fresh shell, and the `dotenv`
  plugin re-exports the stale empty values every time.

- **The Origin check compares against `PUBLIC_BASE_URL` exactly** (scheme,
  host, port) — step 2.8. Any write from a browser whose origin differs gets
  403 `bad_origin`, so production must set it to the real HTTPS URL. Deferred
  from 2.8 on purpose: `/readyz` still can't detect a dead Odoo key (see above).
- **`audit_log` writes are best-effort** (failure logs at ERROR, never blocks
  the employee's entry) and unauthenticated mutation attempts aren't audited.
  Its migration (`211bfd794469`) needs `alembic upgrade head` like the outbox's.

- **The Playwright suite (`web/e2e`) needs employee 1 unlocked, and refuses to
  start otherwise** — with a message, in seconds, instead of 30 s timeouts. Its
  lock tests "restore" whatever lock they find, so a stale lock used to
  perpetuate itself. Everything the suite creates (Odoo lines, outbox rows)
  carries the `e2e-suite` note prefix (`web/e2e/fixtures.ts`); fixtures remove
  exactly that at the start of a run and after every test, so it leaves nothing
  behind. New e2e tests must import `test`/`expect` from `./fixtures` and tag
  what they create. If the guard trips and the lock is not deliberate, clear
  `hr.employee.last_validated_timesheet_date` on employee 1 and rerun.

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

## Running the app (Phase 1+)

```bash
docker compose up -d              # api, worker, web (one-shot build), db, caddy
curl http://localhost/api/healthz | jq .
open http://localhost/
docker compose down -v            # full reset, including the Postgres volume
```

**No auto-migrate on startup yet** (step 2.3) — after any `down -v` (or a
genuinely fresh DB volume), run the Alembic migration by hand before the
outbox works:

```bash
cd api && set -a && source ../.env && set +a && \
  export DATABASE_URL="postgresql+psycopg://tti:${POSTGRES_PASSWORD}@localhost:5432/tti" && \
  uv run alembic upgrade head
```

(`db`'s port is published on the host's loopback only (`127.0.0.1:5432`,
`docker-compose.yml` — never on all interfaces, see `docs/deploy-staging.md`), so
this runs from the host, not inside a container. Worth wiring into container startup
before Phase 3 deployment; not done yet.)

This machine has no Docker Desktop — it uses **Podman** with Docker-CLI
compatibility (`DOCKER_HOST` in `~/.zshenv`, machine set to **rootful** so
Caddy can bind 80/443). `docker`/`docker compose` work unmodified; see the
step 1.1 commit for the setup if it needs redoing on another machine.

**oh-my-zsh's `dotenv` plugin quirk:** this shell auto-sources `.env` on
every `cd` into the repo (the `dotenv` plugin). If `.env` gets edited after
a shell was already sitting in this directory, that shell can be carrying
stale exported values (observed: an empty `POSTGRES_PASSWORD`/`DATABASE_URL`
persisting long after `.env` was fixed, silently overriding
`docker compose`'s own `.env` loading, which resolves values correctly).
If `docker compose` complains a variable is missing when `.env` plainly has
it: `unset POSTGRES_PASSWORD DATABASE_URL` (or whichever variable) before
the command, in the same shell invocation.

## Commit hygiene

`.env` must never be staged. If a tool (Codacy, an IDE plugin, etc.) drops
config into the repo root uninvited, decide deliberately whether it should
be tracked or gitignored — don't let it ride along on an unrelated commit.