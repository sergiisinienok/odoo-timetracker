# Odoo Time Tracker

**A time-logging app for employees, writing straight into Odoo timesheets, invoiced to clients at each person's rate.**

| | |
|---|---|
| **Status** | Draft v9 — every unbillable project open to everyone, no special internal project (10 Oct 2026, decision 0014); v8 — tasks and three-level billability (29 Sep 2026, decision 0011); v7 incorporated review comments from Yarik |
| **Owner** | Sergii |
| **Target system** | Odoo 19 Enterprise (Odoo Online) |
| **Billing model** | Time & materials, rate per employee or monthly flat rate, USD only |
| **Target** | September 2026 |
| **Date** | 1 Sep 2026 |

---

## What changed, and why it matters

Earlier drafts assumed employees would keep logging time in spreadsheets and that the work was an integration that reads them. The team has decided to remove spreadsheets from the process entirely and replace them with a small web application employees use to log time, which writes into Odoo directly.

That decision deletes more work than it adds. Gone from scope: the Google Sheets reader and parser, the reconciliation engine, the mapping registry, the Odoo Spreadsheets migration path, and the nightly sync along with the window in which two systems could disagree.

What it adds is a product to build and operate. That is a real cost, and it is worth paying because it fixes the one thing no integration could: **the moment of entry**. A spreadsheet cannot ask a question, validate an answer, or refuse a bad one. An app can, which is what finally makes billable and non-billable time separable.

### v8: projects, tasks, and three levels of billability

After Phase 2, and before the pilot, the model was refined (`docs/decisions/0011-tasks-and-three-level-billability.md`). Time is now logged against a **project and a task**, and billability is decided at three levels, each overriding the one above: the **project** sets the default, the **task** can override it, and the **approver** can override any single time record in Odoo. The employee still never answers whether time is billable. The paid/unpaid pair of picker entries is gone, because an unbillable task does the same job with less to explain. The sections below are amended to match; where v7 text is replaced, the change is marked **(v8)**.

---

## Why

The old process was manual at exactly the point where money is at stake. Employees logged date and hours in personal spreadsheets; someone opened each one at month end, totalled it, and produced client invoices by hand. Four costs recurred:

- **Effort that scales with headcount.** Every person on a client is another sheet to open, total, and transcribe.
- **No validation at entry.** Nothing catches a missing week, a 14-hour Sunday, or a date in the wrong year until it reaches an invoice.
- **No single source of truth.** Hours in Sheets, contracts and rates elsewhere, invoices in Odoo.
- **No separation of billable from internal time.** A spreadsheet row is just hours. Internal work, bench time, and PTO look exactly like client work, so excluding them depends entirely on someone remembering.

That last point is what the team surfaced in discussion, and it is why the design changed rather than being patched.

---

## What we are building

Two things, and deliberately no third.

**1. A time-logging web application.** Employees sign in with their Google Workspace account and log hours against their current assignments. Responsive, so it works from a phone browser. Two views: the current period, and a listing of everything they have logged.

**2. Odoo configuration for timesheet-based invoicing.** Service products, projects, sales orders with a line per billed person carrying that person's rate, one internal project for everything non-billable, and the native monthly timesheet validation.

There is no third component. The app writes each entry into Odoo as it is saved, through one integration user over the external API. **Odoo holds the time data; the app is a front end to it.** No second database of record, no sync job, no reconciliation, no drift.

---

## The core idea: assignments, not categories

An employee is never asked whether their time is billable. That is an accounting question, and asking it of the person logging hours is what made the spreadsheet approach unfixable.

Instead, the app asks what they worked on, and offers only their own **assignments**:

| Kind | What it is | Where the hours land in Odoo | What the client is invoiced |
|---|---|---|---|
| Client, time & materials | This person, on this client engagement, at their contracted hourly rate | The engagement's project, against **their own sales order line** | Hours × their rate |
| Client, monthly flat rate | This person allocated to a client for a fixed monthly amount | The engagement's project, against their own sales order line | The agreed monthly amount, whatever the hours |
| **Client, unpaid** | Work for a client that is deliberately not charged — rework, ramp-up, goodwill, overrun we absorb | The engagement's project, **with no sales order line** | Nothing |
| Unbillable project **(v9, replaces Internal)** | Not attached to any client — internal work, bench, PTO, anything else ops sets up as an unbillable project | Any unbillable project, chosen by its own name; open to every employee; no sales order line | Nothing |

Billability is a property of the assignment, decided once when someone is put on a client, and never re-decided per entry. There is no billable toggle in the interface, because there is nothing for an employee to get wrong.

**(v8)** The table above describes v7. From v8 the employee picks a **project and a task** from the projects they are assigned to, and billability is resolved in three levels:

| Level | Set by | Where | Effect |
|---|---|---|---|
| Project | Ops | Odoo project form | The default for every task on it |
| Task | Ops | Odoo task form | *Same as project*, *Billable*, or *Not billable*; overrides the project |
| Time record | Approver only | Odoo timesheet line | Overrides the task for that one line, e.g. when a customer agrees to pay for some hours of an otherwise unbillable task |

There is still no billable toggle in the interface, and the employee is still never shown the answer. What changed is where the answer lives: in the task, and so in how ops structures the work, not only in which assignment someone holds. In Odoo, billable still means exactly one thing: the line carries a sales order line.

**Billing mode is invisible to the employee.** Someone on a flat-rate engagement logs time exactly as someone on time & materials does — same picker, same fields, same habit. The difference lives entirely in the Odoo configuration behind the assignment, which is where a commercial term belongs.

### Unpaid time on a paying client

Not all work for a client is charged to them. Rework we own, ramp-up on a new joiner, goodwill, an overrun absorbed rather than argued about — these are real hours, spent on that client, that nobody intends to invoice. Earlier drafts had nowhere to put them: a client assignment always billed, and the only alternative was the internal project, which would have attributed the effort to nobody.

So each client engagement produces **two entries in the picker** — the client, and the client marked as unpaid. Same project either way; the difference is that the unpaid entry carries no sales order line, which is exactly how Odoo represents a non-billable timesheet.

This keeps the principle intact. The employee is still not answering an accounting question or flipping a switch; they are choosing what they worked on from a list, and one of the choices happens to be "this client, not charged." Whether a given hour belongs there is a judgement their approver can see and correct, which is the right place for it.

The payoff is in the numbers. Absorbed effort now sits on the client's own project rather than vanishing into an internal bucket, so the margin view for that engagement tells the truth — including on flat-rate work, where absorbed hours are the whole story.

**(v8)** The two-entries-per-client mechanism is replaced. Absorbed work is logged on an **unbillable task on the client's project**, such as "Rework" or "Ramp-up", which ops creates. The payoff above is unchanged, and sharper: absorbed effort is now attributed to the client *and* to the kind of work it was. Whether a given hour belongs there is still a judgement the approver can see and correct, now by overriding the single line in Odoo.

**The assignment list comes from Odoo, not from a registry we maintain.** A person's billable assignments are exactly the projects where they have a rate mapping on the sales order — configuration that must exist for invoicing to work at all. The app reads it live. Putting someone on a new client is one action in Odoo, and their picker updates.

### Flat-rate engagements still need every hour

On a flat-rate engagement the invoice does not come from the timesheet, which raises the obvious question of why anyone should log time at all. Three reasons, and they are the reasons this whole system exists:

- **Margin.** A fixed monthly amount is only profitable at a certain level of effort. Hours are the only way to know whether an engagement is comfortable or quietly underwater, and by how much.
- **Evidence of delivery.** When a client asks what they got for the month, the answer should be a record rather than a recollection.
- **One habit, not two.** If flat-rate people logged time differently — or not at all — the process would fork, and the fork would be where mistakes live. Everyone logs the same way.

The practical consequence for the approver: on a flat-rate assignment, hours materially above the level the price assumes are a commercial signal, not a data error. Surfacing that is worth more than anything else the reporting could do, and it is the one thing the old spreadsheet process could never show.

### What an assignment is called

Employees see **the client's name**, taken from the project's customer in Odoo. No new vocabulary, no internal project codes, nothing to learn. Where one client has more than one engagement, the app appends the project name to keep them apart; that is the only case where a project name is ever shown.

### The default, and the rare second client

Most people are on one client for months at a time, so the picker is a default with an override rather than a decision each time. **The default comes from a field on the employee form in Odoo** — the same place everything else about a person is administered — so ops changes it when someone moves, and nobody touches the app to do it.

Odoo has no stock "default project" field on the employee, so this is added with Studio (included in Enterprise, supported on Odoo Online) as a Many2one to `project.project`, and read over the API like any other field. Two rules keep it honest: the default must be one of that person's actual assignments, and the app refuses to save an entry against an assignment the employee does not hold.

Being on two clients at once is rare but real. The picker handles it as an override on an otherwise pre-filled field — a second client should cost a tap, not restructure the interface for everyone else.

---

## The application

### Sign-in and identity

Google sign-in, restricted to the company Workspace domain. The account's email must resolve to an active employee record in Odoo; anything else is refused. No local passwords, no separate account to provision.

An employee sees and edits only their own entries, and only in an open period.

### View 1 — Current period

The working surface, and where people spend all their time.

- The open month, day by day, with a quick add: assignment, hours, optional note
- Running totals — month to date, and per assignment
- Days with nothing logged made visible, so gaps are noticed during the month rather than at close
- Period status shown plainly: open, or approved and locked
- Edit and delete freely while the period is open

### View 2 — Time tracking listing

Everything the person has logged, across periods. Filter by month and assignment, search notes. Closed periods are read-only. This is where someone answers "what did I do in June" without asking anyone.

### An entry

| Field | Required | Rule |
|---|---|---|
| Date | yes | The working day in the employee's own timezone. Defaults to today. Must fall inside the open period and inside the assignment's validity dates. |
| Hours | yes | Quarter-hour increments. The day's total may not exceed the configured daily maximum, default **10 hours**. |
| Project **(v8, replaces Assignment)** | yes | **(v9)** The projects they are mapped to, plus every unbillable project; pre-filled with their Odoo default. Refused if neither. |
| Task **(v8)** | yes | An open task on that project, created by ops in Odoo; pre-filled with the task they last used on it. Lines logged before v8 show "No task" and need one when edited. |
| Note | no | Free text, carried into the Odoo timesheet description |

**On the daily cap.** It is a hard limit, not a warning, because a sanity check nobody has to obey is not a check. It is configurable rather than fixed at ten, and raising it is an ops action. The trade-off is deliberate: a genuine twelve-hour day requires a conversation, which is the correct amount of friction for something that should be rare and is worth someone knowing about.

**No money, anywhere.** The app shows hours and never rates, costs, or amounts. Employees have no view of what their time is billed at.

---

## How an entry reaches an invoice

1. **Log.** The employee saves an entry in the app.
2. **Write through.** The app immediately creates the corresponding Odoo timesheet line via the external API and keeps its id. An edit updates that line; a delete removes it. The app never holds hours that Odoo does not have.
3. **Accumulate.** Billable hours land against the employee's own sales order line and appear as delivered quantity. Non-billable hours — on an unbillable task, a client project's or the internal project's — carry no sales order line, so no sales order can reach them. **(v8)** The app decides which at write time from project and task; the approver can change it per line in Odoo.
4. **Approve.** At month end, one responsible person reviews and validates the whole month in Odoo — every employee, every client, one pass. **Whether a month is complete is the approver's judgement**, not something employees declare, so the app has no submit button and nobody is waiting on anybody.
5. **Invoice and lock.** Invoices are created from the sales orders. The period is closed and the app makes it read-only.

**The write queue.** Write-through has one failure mode worth engineering for: Odoo being briefly unreachable when someone hits save. The app holds a durable queue of pending writes and retries, showing the entry as saved-but-not-yet-synced. This is a queue, not a second system of record — nothing is ever read back from it, and it drains to empty. Without it, an Odoo hiccup loses an employee's input, which is the fastest way to lose their trust in the tool.

---

## What lands in Odoo

| From the app | Odoo object | How it is set |
|---|---|---|
| One entry | `account.analytic.line` | Timesheet line: date, hours, employee, project, task, description, and the sales order line it bills to |
| Signed-in user | `hr.employee` | Resolved from the Google account's email; never guessed |
| Assignment (client, T&M) | `project.project` + `sale.order.line` | The engagement's project, and that employee's own order line carrying their hourly rate, invoiced on delivered timesheets |
| Assignment (client, flat rate) | `project.project` + `sale.order.line` | The same, but the order line is priced as a fixed monthly amount and invoiced on its own schedule; hours are recorded against it without driving the amount |
| Assignment label | `res.partner` | The project's customer — the client name the employee sees |
| Default assignment | `hr.employee`, Studio field | Many2one to `project.project`, administered on the employee form |
| Assignment (client, unpaid) | `project.project` | **(v8: replaced by unbillable tasks)** The client's own project, with the sales order line left empty — Odoo's representation of a non-billable timesheet |
| Task **(v8)** | `project.task` | Created by ops on each project; carries the billable override (*Same as project* / *Billable* / *Not billable*), likely a Studio field. Written to the timesheet line's task |
| Project billable default **(v8)** | `project.project` | The project's own billable setting |
| Time-record override **(v8)** | `account.analytic.line` | The approver sets or clears the line's sales order item in Odoo; the app never undoes it |
| Unbillable projects **(v9)** | `project.project` | As many as ops wants, each with no sales order behind it and its own ops-defined tasks (PTO, Bench, Training, Internal work …); open to every employee |
| Rates | `product.pricelist` | Price per role product per client; the sales order line takes its price from there |
| — | `product.product` | Service product, Invoicing Policy **Based on Timesheets**, Create on Order **Project & Task** |
| — | `account.move` | The client invoice, generated from the sales order at close |

**Per-employee rates come from the Odoo pricelist.** Odoo prices an invoice line from the sales order line, not from whoever logged the hours, and the mechanism for a per-person rate is to map each employee to their own sales order line in the project's invoicing configuration. The question is where that line's price comes from, and the answer is the standard one: **a service product per role, priced per client through Odoo's pricelists.**

Concretely — a service product for each role we sell (senior engineer, QA, PM), a pricelist per client setting what that client pays for each of them, and one sales order line per allocated person using their role's product. The line prices itself, and each employee is mapped to the line matching their role.

This is better than typing a rate onto each order line, and not only because it is standard. Rates become visible in one place per client instead of scattered across order lines, a repricing at renewal is a pricelist edit rather than an archaeology exercise, and new engagements inherit the right numbers by default.

The limit worth knowing: two people in the same role on the same client at different rates cannot both take the role's pricelist price. That case needs either a person-specific product or a manual price on the line — supported, but an exception, and one that should be visible rather than routine. **Rates are fixed for the life of a contract and everything is USD, so no dated pricing or currency handling is needed.**

**This is still the first thing to prove in a sandbox — the billing model and the app's assignment list both rest on the employee-to-order-line mapping, and now on the pricelist feeding it.**

**The two billing modes are one Odoo setting apart.** Both kinds of client assignment are the same shape: a project, a sales order, one line per allocated person. What differs is the service product's invoicing policy on that line — *based on timesheets* for time & materials, *prepaid/fixed price* for a flat monthly rate. Because the employee-to-order-line mapping is what the app reads to build someone's assignment list, it works identically for both, and the app needs no concept of billing mode at all.

The assumption worth naming: a flat rate is treated as **per allocated person per month**, one order line each, matching how the staffing model works. If a flat rate is ever agreed for a whole team as a single figure, that engagement needs one line and a rule for which person's hours attach to it — solvable, but not the same configuration, so flag it if it happens.

**The integration user needs approver rights.** Odoo's timesheet model raises an access error when a user writes a line belonging to another employee unless they hold `hr_timesheet.group_hr_timesheet_approver`. The integration account must therefore be an internal user with Timesheets approver access, its API key stored as a secret and rotatable. It is a privileged account and should do nothing else.

---

## Period locking — the app has to enforce it

This was checked against the Odoo source, and the finding changes the design.

Odoo Community defines the hook but not the behaviour: `account.analytic.line` has a computed `readonly_timesheet` field driven by `_is_readonly()`, which returns `False` and is, in Odoo's own comment, *"overridden in other timesheet related modules."* Enterprise's `timesheet_grid` is that module, and it is closed source, so what the override actually sets can only be seen on the live instance.

Two conclusions follow, and the second is the important one:

- **`readonly_timesheet` is computed relative to the calling user.** Our integration account holds approver rights, so the flag may well read `False` on a line that is validated — approvers are allowed to edit. It is therefore not safe as the app's lock signal on its own.
- **Validation marks lines; it does not make them immutable to the API.** Stock Odoo restricts editing validated timesheets in the grid interface, but the records remain writable — third-party modules exist specifically to prevent deleting validated timesheet lines, which would be pointless if Odoo already refused. **So the app must enforce period locking itself and must not assume Odoo will refuse a bad write.**

A spike script (`spike_odoo_timesheet_lock.py`) accompanies this document. It introspects the live instance for validation-related fields on the timesheet line, employee and company, shows what they read as on real lines, and is run twice — once as the integration user and once as an ordinary employee — to reveal whether the readonly flag is user-relative. Ten minutes, and it names the exact field the app should read.

---

## The licensing question — check this before banking the saving

Odoo Enterprise is priced per login. Odoo's own guidance is direct: any employee who needs a login to Odoo needs a user license, and employees who complete timesheets by logging into Odoo **are** counted. The same guidance explicitly permits the alternative this design uses — nominating one login to enter timesheets on behalf of other employees.

Our integration user is exactly that nominated login, automated. On a plain reading, employees who only ever touch the app never need Odoo seats, and for a company of this shape that is the difference between a handful of licenses and one per head.

**Verify it in writing with your account manager before treating it as settled.** The clearest public statement of this is a forum answer from Odoo's technical marketing team, not the subscription agreement, and the amount at stake makes it worth a direct question. If the answer is unfavourable, the app is still worth building — it fixes entry-time classification and keeps the ERP out of everyone's daily workflow — but the business case changes materially, so ask early.

---

## Joining and leaving

Assignments carry start and end dates, and the app enforces them: someone who joins a client mid-month can log from their assignment start date and not before.

Departures are the awkward case, and the awkwardness is not in our system. A leaver keeps app access until their final month is validated, which means their **Google Workspace account must stay active for that window** — if IT disables it on their last day, they cannot sign in to complete the month, and their final hours have to be entered by the approver instead. Worth agreeing with whoever runs offboarding before the first person leaves, not after.

---

## Month-end close

| When | What | Who |
|---|---|---|
| Throughout the month | People log time; entries appear in Odoo as they are saved | Employees |
| Last working day | Reminder to complete the month | Ops |
| Day 1–2 | Judge the month complete, review and validate it in Odoo | Approver |
| Day 2–3 | Create and send invoices from the sales orders — hours × rate for time & materials, the agreed amount for flat rate; period locked | Finance |
| After lock | The app shows the period read-only; corrections go through the approver in Odoo | Approver |

The approver also owns anything the app flags during the month — an employee with no assignment, a rejected entry, a person with a suspiciously empty week.

### When a mistake is found after the month closes

An earlier draft said there was simply no correction path. That was too absolute — mistakes happen, and a process with nowhere to put them just pushes them somewhere invisible. The honest position is that **the app has no correction path, and the company does.**

| When the mistake is found | What happens |
|---|---|
| Before validation | The approver edits the timesheet directly in Odoo. Routine, no ceremony. |
| After validation, before invoicing | The approver corrects it in Odoo before the invoice is raised. Still cheap. |
| After the invoice has gone out | The timesheet is corrected in Odoo so the record is true, and the money is settled separately — a credit note, or an adjustment on the next invoice. A commercial decision, taken by a person. |

Three things hold in every case. The employee never regains access to a closed month — corrections are the approver's, in Odoo. Every correction leaves a trail, because Odoo records who changed what. And the timesheet is always made true even when the invoice is settled some other way, so the hours a client was charged for and the hours we actually worked never diverge in the record.

---

## Decisions

- **The app writes through to Odoo; Odoo is the only record.** No second database, no sync, no reconciliation. The app keeps a durable write queue for retries and nothing more.
- **Assignments carry billability and billing mode.** Employees pick what they worked on, never whether it is billable, and never see whether an engagement is time & materials or flat rate. Both modes are the same configuration with a different invoicing policy on the sales order line. **(v8)** Billability now comes from project and task, not the assignment alone; billing mode is still the assignment's, still invisible.
- ~~**Every client engagement offers a paid and an unpaid entry.**~~ **(v8)** Replaced by unbillable tasks on the client's project. Absorbed work stays attributed to the client whose project it was spent on, instead of disappearing into an internal bucket.
- **(v8) Time is logged against a project and a task; billability has three levels.** Project default, task override, and a per-line override by the approver in Odoo. The employee is never asked and never shown. Tasks are created by ops, never from the app. See decision 0011.
- **Rates live in Odoo pricelists**, on a service product per role, priced per client. A rate typed onto an order line is an exception, not the norm.
- **Flat-rate engagements log time too.** Hours do not drive those invoices, but they are the only source of margin and delivery evidence, and one habit for everyone is worth more than the hours saved by exempting people.
- **The assignment list is read live from Odoo**, and the per-person default lives on the employee form as a Studio field. No separate registry to maintain or drift.
- **Employees see client names.** Project names appear only to disambiguate two engagements with the same client.
- **The app enforces period locking itself.** Odoo's validated flag is the signal, not the guard.
- **Google Workspace sign-in only, resolved to an Odoo employee.** No passwords, no provisioning, no access without both.
- **Approval stays native and stays the approver's call.** No employee submit step; the approver decides when a month is done and validates it in Odoo.
- **Quarter-hour increments, configurable daily cap defaulting to ten hours**, enforced as a hard limit.
- **Hours only, never money.** The app has no view of rates or amounts.
- **The integration runs as an external service** with a dedicated, privileged, rotatable API key. Odoo Online does not host custom modules.
- **One approver, one monthly pass**, covering every employee and client.
- **The month is a hard boundary in the app, not in the company.** Employees cannot touch a closed period, and the app never reopens one. Mistakes found afterwards are corrected by the responsible person directly in Odoo, deliberately and with a record. See below.
- **Unbillable projects, open to everyone.** Non-billable time is excluded from invoices. **(v8)** It is broken down by ops-defined tasks. **(v9)** There is no single internal project any more: ops creates as many unbillable projects as they like and every employee sees them all, by project name.
- **Responsive web, one codebase.** No native apps.
- **No historical migration.** The app starts with a current month; old spreadsheets are archived as they are.

---

## What done looks like

- **Zero** spreadsheets in the time-tracking process
- **Zero** non-billable hours reaching a client invoice
- **Visible** effort against price on every flat-rate engagement, for the first time
- **Attributed** absorbed work — unpaid hours sit on the client they were spent on, not in a bucket
- **100%** of billable hours in Odoo as they are logged, not at month end
- **< 30 minutes** of human time to produce a full billing run's invoices
- **One** monthly approval pass covering every employee and client
- **Under a minute** for an employee to log a normal day, from opening the app to done
- **Live** consumed-hours view per client, available any day of the month

---

## Still open

Nothing blocks a build plan. Three items to settle as work starts:

1. **Prove both billing modes in a sandbox** — a timesheet-invoiced order line and a fixed-price monthly one, on the same project, each mapped to a different employee. The billing model and the assignment list both depend on the employee-to-order-line mapping behaving identically for the two. First task in Phase 0.
2. **Run the locking spike and name the validation field.** Decides how the app reads period state.
3. **Credit note, or adjustment on the next invoice?** For mistakes found after an invoice has gone out. A commercial preference rather than a technical one, but worth agreeing once so finance is not deciding case by case.
4. **Hosting and data-protection posture — parked by decision.** Working hours are personal data about employees, so retention, access, and location need writing down once. Deferred until the application itself is settled, not forgotten.

---

## Phases

| Phase | Name | Content |
|---|---|---|
| 0 | Odoo foundation | Configure role service products in both invoicing modes, a client pricelist, a test client engagement, per-employee order-line mapping, the internal project, and the Studio default-assignment field. Confirm that a timesheet with no order line reads as non-billable. Create the integration user with approver rights and prove writes for two different employees. Run the locking spike. Ask Odoo the licensing question in writing. |
| 1 | Walking skeleton | Google sign-in, employee resolution, assignments read from Odoo, one entry written through and visible in Odoo. One employee, one client, nothing else. |
| 2 | The product | Both views, full entry lifecycle, validation rules, the write queue, period locking. Usable end to end. |
| 2b | Tasks and billability (v8) | Re-run the probe suite on the real sandbox; project and task pickers; billability resolved from project and task, overridable per line by the approver in Odoo. |
| 3 | Pilot | A handful of employees run one full month in the app while their spreadsheets continue in parallel. Compare the two at close; invoices still produced the old way. |
| 4 | Rollout and cutover | Everyone moves to the app, spreadsheets are retired, invoicing runs from Odoo. |
| Later | Whatever the pilot proves is missing | An approver view, utilisation reporting, PTO, chat reminders — none of it committed to now. |

---

*References: [Invoicing based on time and materials — Odoo 19.0](https://www.odoo.com/documentation/19.0/applications/sales/sales/invoicing/time_materials.html) · [Odoo on what counts as a licensed user](https://www.odoo.com/forum/help-1/what-counts-as-a-user-for-licensing-purposes-do-employees-count-115229) · [`hr_timesheet` timesheet model, odoo/odoo 19.0](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/hr_timesheet/models/hr_timesheet.py) · [External API — Odoo documentation](https://www.odoo.com/documentation/18.0/developer/reference/external_api.html)*
