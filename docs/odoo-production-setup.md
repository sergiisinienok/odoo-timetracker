# Configuring Odoo for the time tracker — production

Target: `https://particlesglobal-1.odoo.com` (Odoo 19, SaaS, Enterprise).
Companion to `docs/deploy-production.md` (step 1 there points here). Draft 2026-10-17.

**Who does this:** a human with an Odoo administrator login. The app never creates any of it,
and `tools/prod_preflight.py` only reads. Read this once before touching anything.

**How sure this is.** The *what* (which records, which field names, which values) comes from the
Phase 0 and 2b probes and decisions 0001–0015, all run against the **trial**
(`edu-timetracking.odoo.com`). The *where to click* is written from how Odoo 19 normally lays
things out and was not walked through on this instance, so menu names may differ slightly. Where a
step says **STOP**, a difference from what is described is a finding to report (project ground rule
5), not something to work around.

## What the app needs, in one paragraph

Employees sign in with Google; the app finds them by `hr.employee.work_email`. It reads which
projects and tasks they may log against, then writes **timesheet lines**
(`account.analytic.line`) through one service account, the *integration user*. Billing falls out
of Odoo's own configuration: a line with a sales order line (`so_line`) is billable, one without
is not. So the app needs: the integration user, three custom Studio fields, and your projects,
tasks, sales orders and employee mappings set up the way Odoo already expects for timesheet
invoicing.

---

## Part A — what the app itself requires

Do these in order. Each ends with how to tell it worked.

### A1. The integration user

Settings → Users & Companies → Users → New.

- A **dedicated** login (for example `integration@particles.global`). Not a person's account:
  their departure or password reset must not break timesheets for everyone.
- User type **Internal User**.
- Set the user's **Email** (the daily digest uses it as sender).
- Access rights (Odoo's "Access Rights" tab on the user), exactly these, and note the names you
  pick:

  | Area | Set to | Why |
  |---|---|---|
  | Timesheets | **Administrator** | write lines on behalf of any employee; read validation state |
  | Project | User (Administrator also works) | read projects and tasks |
  | Sales | **User: All Documents** | read every client's order lines. **Never "Own Documents Only"**: it silently hides every order this user didn't sell |
  | `mail.mail` | **read + create** | the daily digest (decision 0009) |

  The `mail.mail` grant is the awkward one. `mail.mail` is normally restricted to Settings /
  Administration, and a service account shouldn't be an administrator for one email a day. The
  trial's integration user (uid 5) has the grant, but **decision 0009 didn't record which group
  gives it.** Open uid 5's Access Rights tab on the trial, copy the extra group, and then **write
  its name into decision 0009** so nobody has to search again. Keep the grant minimal: `write` and
  `unlink` on `mail.mail` stay denied, and the preflight warns if they aren't.

**How you know:** after A2, `tools/prod_preflight.py` shows PASS on all of `Timesheets /
Administrator`, Project access, Sales access, and `mail.mail read`/`create` (with `write`/`unlink`
denied). **STOP** if the Sales line says "Own Documents Only".

### A2. The API key

Log in *as the integration user* → avatar → Preferences → Account Security → **New API Key**.

- Name it `production <date>` so a rotation can tell keys apart.
- Odoo shows it **once**. It goes straight into the `./ops/configure-prod-env.sh` prompt
  (hidden input), never into chat, a ticket, a commit or a shared note.
- Production's key is its own. Do not reuse the trial's or staging's.

### A3. Three Studio fields

Turn on developer mode (Settings → Activate the developer mode), then use Studio. Add exactly these,
then **check the technical names** (developer mode shows them on the field):

| On | Label (suggested) | Type | Expected technical name | Notes |
|---|---|---|---|---|
| `hr.employee` | Default project | Many2one → `project.project` | `x_studio_default_project` | The project pre-selected when an employee opens the app |
| `account.analytic.line` (Timesheet) | Timetracking app entry id | Char | `x_studio_timetracking_app_entry_id` | **Indexed**. Not shown to users. It stops a retried request from creating a duplicate line, which is the failure this project exists to prevent |
| `project.task` | Billable? | Selection | `x_studio_billable` | Options **exactly** `Same as project`, `Billable`, `Not billable` (the stored keys equal the labels); default `Same as project`; not required, not read-only |

- **Indexed:** Studio doesn't expose it; set it under Settings → Technical → Fields → the field →
  *Indexed*. The API can't confirm it. The preflight prints a WARN every time, and the check is you
  looking at the field once.
- **STOP** if Studio generates a different technical name (it names from the label, so a different
  label gives a different name). The names live in `odoo_profile.json`, and changing them is a profile
  change that goes through a decision record, not an edit to make the preflight pass.
- Task field: existing tasks will read blank. The app treats blank as *Same as project*, so there
  is nothing to backfill.

**How you know:** preflight PASS on `hr.employee.x_studio_default_project`,
`account.analytic.line.x_studio_timetracking_app_entry_id` and `project.task.x_studio_billable`,
and PASS on the three `task billable option` lines.

### A4. Employees must be findable

Employees app. Sign-in looks for **exactly one active employee** whose **Work Email** equals the
person's Google address (an exact match, so keep them identical, including case). Zero
matches or two matches both refuse the sign-in.

For every pilot employee check:

- **Active**, and **Work Email** set and unique.
- **Timezone** set (if empty the app falls back to UTC, and "today" can be the wrong day).
- Their email domain is `particlesglobal.com`, which is the only domain the app admits
  (`GOOGLE_HOSTED_DOMAIN`).
- Optional: **Default project** (A3) filled in, so the form opens on their usual project.

**How you know:** the preflight lists employees with no `work_email`, outside the domain, with no
timezone, or sharing an email (that last one is a FAIL).

---

## Part B — the commercial setup the app relies on

Your production Odoo probably already has most of this. **Check it, don't recreate it.** The app
reads Odoo's own invoicing configuration and adds none of its own, so these have to be right.

### B1. Role products

Per role you sell (for example Senior Engineer, Engineer, QA, PM): a **Service** product.

- **Time-and-materials roles:** Invoicing Policy **Based on Timesheets**, Create on Order
  **Project & Task**.
- **Flat-rate roles:** the same roles with Invoicing Policy **Prepaid/Fixed Price**, named so the
  difference is obvious on an order line.
- A **pricelist per client** that sets each role's rate for that client. The per-person rate comes
  from the role product on that person's order line.

### B2. The engagement

For each client engagement:

1. A **sales order** with **one line per allocated person**, using that person's role product
   (this per-person line is what makes a rate per person possible).
2. A **project** with **Billable** turned on and **Timesheets** turned on.
3. On the project's **Invoicing** tab, **map each employee to their own order line**. Two people on
   one project get two mappings, two lines, possibly two rates.
   - This mapping (the `project.sale.line.employee.map` rows) **is** the app's definition of
     "the projects this person can bill to". No mapping means the project isn't offered.
4. Confirm the order. Dates for an assignment live on the order line; the app reads them from
   there.

**STOP** and report if the Invoicing tab's mapping isn't backed by `project.sale.line.employee.map`
in this instance. The whole assignment-discovery mechanism rests on it. The preflight doesn't check
this model; the assignment probe does (A5).

### B3. Tasks and billability (Phase 2b)

Billability is decided at three levels, each overriding the one above (decision 0011):

| Level | Who sets it | Where |
|---|---|---|
| Project | You | the project's **Billable** toggle |
| Task | You | `Billable?` on the task: *Same as project* / *Billable* / *Not billable* |
| One timesheet line | The approver only | the line's **Sales Order Item**, in Odoo's timesheet views |

Every project that employees will log against needs **open tasks**: not archived, not in a closed
stage. Employees pick a task on every entry and **cannot create tasks**; a project with no open
task shows "This project has no open tasks yet. Ask ops to add one." Use tasks for things like:

- On client projects: the work itself, plus an *unbillable* task such as `Rework` or `Ramp-up`
  (this replaces the old "unpaid" entry).
- On a flat-rate engagement: billability is a margin signal only; the invoice is the fixed amount
  whatever the hours.

### B4. Unbillable projects (everyone sees these)

Decision 0014: **every active project with Billable off and Timesheets on is offered to every
employee**, mapped or not, with all its open tasks. Use this for PTO, bench, training, internal work,
pre-sales: one project each, each with its own tasks (all *Not billable*).

Two consequences to know before you create them:

- **Anything on such a project is visible to all employees**, by name and task. Don't put
  confidential work there.
- Odoo's own built-in company *Internal* project is hidden from the app on purpose. Create your own.

If an unbillable task is marked *Billable* on a project the employee isn't mapped to, the line is
saved **unbillable** and reported in the daily digest (there's no order line to bill against).

### B5. The approver's workflow (nothing to configure, but agree it)

- The approver validates a month in the Timesheets grid. That sets the employee's
  `last_validated_timesheet_date`, and the app then treats everything up to that date as locked and
  read-only for the employee.
- Validated lines stay writable over the API (probed), so **the app is the only guard**. Don't rely
  on Odoo to refuse an edit.
- An approver's change to a line's Sales Order Item is respected: later employee edits of hours or
  the note leave it alone, and moving that line to another project or task is refused with "The
  approver has set how this line is billed". This works because the browser UI marks the line
  (`is_so_line_edited`); a bare API write doesn't, which is why step A5's hand test matters.

---

## Part C — prove it before the pilot

The three **Odoo-side** tests; each needs a person with an admin login in a browser, and the first
two create data in production. **Do these only on a clearly named throwaway setup** (a customer
`ZZ App Test`, a test project and order, a test employee), approved by the owner beforehand, and
archive it afterward. Never run them against a real client's order.

### C1. Read-only check

```
set -a && source .env && set +a        # a shell whose .env points at particlesglobal-1
python3 tools/prod_preflight.py
```

Exit 0, no FAIL. Read every WARN. A user who holds "Own Documents Only" and not "All Documents"
shows as a FAIL on `integration user: Sales scope`.

### C2. The probe suite

Two groups. **Do not run the second group until its ids are changed** (see below).

**Read-only, safe on production as they are** (they only call `fields_get`, `read`, `search_read`):

```
python3 tools/probe_assignments.py <project id>      # takes a PROJECT id, not an employee id
python3 tools/probe_products.py
python3 tools/spike_odoo_timesheet_lock.py
```

`probe_assignments.py` prints the employee-to-order-line mappings on that project and resolves
where assignment dates live. Pick a real project that has at least two employees mapped. Its
`Usage` line was wrong in an earlier draft of this guide, which said `--employee`.

**These write, and hardcode the trial's ids. NOT safe to run as they are:**

| Script | Hardcoded | What it would do on production |
|---|---|---|
| `probe_unpaid_line.py` | project 2, employee 1, sale line 1 | create, rewrite and delete timesheet lines for whoever employee 1 is |
| `probe_write_other_employee.py` | project 1 | create, update and delete lines for employees it picks |
| `probe_flat_rate.py` | project 2, expects a hand-added order line | creates an employee and a mapping, logs hours |
| `probe_tasks.py` | project 2, employee 1, sale line 1, internal project 1 | creates tasks, creates and rewrites lines, changes `so_line` |

On the trial those ids were test records; on `particlesglobal-1` they are whatever has that id
(Odoo's own "Internal" project is often id 1). The scripts have to take their ids from the
environment, and point at the throwaway setup (`ZZ App Test` customer, project, order, employee)
created for this, before they run. `probe_tasks.py` already reads `INTERNAL_PROJECT_ID` that way;
the rest don't. That change is a small edit to each script and is its own step, approved by the
owner first (it touches the probes the plan said to run "without modification", and
"unmodified" is exactly what is unsafe here).

Afterwards, every difference from `odoo_profile.json` is explained in `docs/decisions/`
(`tools/build_profile.py` is named by the plan but doesn't exist yet; see `deploy-production.md`
step 3). Re-check, too, whether each trial quirk in `CLAUDE.md` still holds here (the
`has_group()` fault, `create()` returning a list over XML-RPC, the `partner_id` reset, whether
`readonly_timesheet` varies by user). Production is `saas~19.4`; the trial profile is `19.0`, and
`check_access_rights` has already disappeared between them, so expect more.

### C3. The approver hand test (browser, not a script)

This one cannot be automated, because `is_so_line_edited` is set by the browser form, not by RPC:

1. In the Timesheets view, as an approver, on a **test** line, set the Sales Order Item (then, on a
   second line, clear it).
2. Read both lines back over the API: `is_so_line_edited` must be **True** on each.

If it isn't, **STOP**: the app can't tell an override from its own writes on this instance (decision
0013). The trial passed this on 2026-10-09; production must pass it separately.

---

## Part D — the pilot cast (what to set up per person)

Phase 3 wants 3–5 people covering the cases below. For each, before they sign in:

| Case | Set up |
|---|---|
| Time-and-materials | order line on a T&M role product, mapped on a Billable project |
| Flat rate | order line on a fixed-price role product, mapped on a project |
| Two clients | two projects, two order lines, two mappings |
| Takes PTO this month | the unbillable PTO project and a PTO task |
| Logs unbillable work on a client project | an unbillable task such as `Rework` on their client project |

Plus, once during the month, the approver overrides one line's Sales Order Item in Odoo, and the
employee edits that line afterwards (the check that overrides survive).

Every one of them: A4 (email, timezone, active), a default project (optional but kind), and at
least one mapping or access to an unbillable project. **There is no pilot allowlist in the app**
(`deploy-production.md`): every employee who passes A4 can sign in and write real timesheet lines,
whether or not they're in the pilot.

---

## Checklist

- [x] Integration user created, groups set, `Sales` is **All Documents**, `mail.mail` read+create
- [x] Group behind the `mail.mail` grant written into decision 0009
- [x] Production API key created, stored only in `.env`
- [x] Three Studio fields exist with the expected technical names; app-entry-id **Indexed** (by eye)
- [x] Pilot employees: active, unique Work Email in `@particlesglobal.com`, timezone set
- [x] Role products, pricelists, orders, projects (Billable + Timesheets), per-employee mappings
- [x] Open tasks on every project employees will use; unbillable projects exist for PTO/bench/etc.
- [x] `tools/prod_preflight.py` exits 0 on production
- [ ] Probe suite run on the throwaway setup; every difference from the profile explained
- [ ] Approver hand test: `is_so_line_edited` True after set and clear
- [ ] Throwaway customer/project/order/employee archived
- [ ] Owner's go-ahead to write to production recorded in `docs/decisions/`

Then continue at `docs/deploy-production.md`, step 2.
