# 0011 — Time is logged against a project and a task; billability has three levels

Status: accepted by owner 2026-09-29, before the Phase 3 pilot. Implemented
as Phase 2b of `docs/implementation-plan.md`. Nothing in this record has been
probed yet — every Odoo field it names is *(verify)* until step 2b.3 says
otherwise, and the probe wins (ground rule 5).

## What changes

Until now an employee picked an **assignment** — a client project in a paid
or an unpaid variant, or the internal project — and billability was fixed by
which variant they picked. From Phase 2b:

- Every entry names a **project and a task**. The task is required on new
  entries.
- **Billability is decided at three levels, each overriding the one above:**

  | Level | Set by | Where | Meaning |
  |---|---|---|---|
  | Project | Ops | Odoo project form | The default for every task on it |
  | Task | Ops | Odoo task form | *Same as project* / *Billable* / *Not billable* |
  | Time record | **Approver only** | Odoo timesheet line (Sales Order Item) | Overrides the task for one line |

- The employee is still never asked whether time is billable. The app works
  it out from project and task when the line is written; the approver can
  change any single line in Odoo afterwards.

In Odoo the outcome is represented exactly as before: **a line with `so_line`
set is billable, a line without it is not.** The three levels only decide
which of the two a line gets. Invoicing, `timesheet_invoice_type` and the
existing `unpaid_recipe` are unaffected.

## Decisions, as agreed

1. **No billable control in the app.** The app derives billability; the
   time-record override is the approver's, made in Odoo's own timesheet views
   by setting or clearing the line's Sales Order Item. No approver screen in
   the app.
2. **Task overrides project; time record overrides task.** Example the owner
   gave: an unbillable task with three lines, where the customer agreed to pay
   for one — the approver sets that one line billable in Odoo.
3. **The picker shows every open task on the project** — not archived, not in
   a closed stage. Filtering by task assignee is not possible: employees have
   no Odoo users.
4. **Ops creates tasks in Odoo.** The app cannot create them.
5. **A task is required on new entries.** Lines logged before Phase 2b show as
   "No task"; editing one in an open period requires choosing a task.
6. **The "(unpaid)" picker entries are removed.** Absorbed work — rework,
   ramp-up, goodwill — goes on an unbillable task on the client's project
   (e.g. "Rework", "Ramp-up"), which ops creates.
7. **The internal project gets ops-defined tasks** (PTO, Bench, Training,
   Internal work), all unbillable.
8. **The task pre-fills with the one the employee last used on that project**,
   read from their own Odoo lines. No new Studio field for it.
9. **On flat-rate engagements billability is a margin signal only.** The
   invoice is the fixed monthly amount whatever the hours; billable vs
   unbillable hours only separate delivered scope from absorbed work.
10. **Sequencing: before the pilot**, probed against the real
    `particlesg.odoo.com` sandbox, so the pilot runs the model that will go
    live.

## Brief decisions this reverses or changes

| Brief said | Now |
|---|---|
| "Billability is a property of the assignment, decided once … never re-decided per entry" | A property of project and task, decided by ops; overridable per line by the approver, never by the employee. The principle that the employee never answers an accounting question is **kept**. |
| "Every client engagement offers a paid and an unpaid entry" | Removed. Unbillable tasks replace the unpaid entry. |
| "One catch-all internal project. Non-billable time is excluded from invoices, not analysed." | Still one internal project, but its time is now broken down by task. |
| An entry is date, hours, assignment, note | An entry is date, hours, project, task, note. |

## Assumptions made while writing this up (owner did not object)

- **The task-level flag has three values**, not two. With a plain boolean the
  task would always override and the project flag would never matter. Likely
  a Studio selection field on `project.task`, unless step 2b.3 finds something
  native that does the job.
- **A billable line needs an order line to bill against.** The app uses the
  employee's own mapped order line on that project
  (`project.sale.line.employee.map`, as today). If a task resolves billable but
  the employee has no mapping on the project (the internal project, or a
  project billable only through its tasks), the line is written **unbillable**,
  the employee is not blocked, and the case is reported in the daily digest
  for ops to fix the configuration or the approver to set the line by hand.

## Consequences the plan has to handle

- **An employee edit must not undo an approver's override.** If the approver
  set or cleared a line's Sales Order Item, a later employee edit of hours or
  the note must leave `so_line` alone. Odoo's own marker for a manually set
  order line — expected to be `is_so_line_edited` *(verify)* — is how the app
  recognises this. Changing the **project or task** of an overridden line is
  refused (`billing_set_by_approver`): the override was a decision about that
  line's work, and moving it silently would either drop it or carry it to work
  it was never meant for.
- **Setting `task_id` may make Odoo recompute `so_line`** from the task's own
  `sale_line_id` or the employee mapping. That could refill an unbillable line.
  The current `unpaid_recipe` was proven only for lines with no task, so it must
  be re-proven with a task set (step 2b.3).
- **Assignment ids disappear from the API** (`project:<id>:paid`, …). Queued
  outbox rows written in the old shape are converted by the migration, not
  dropped.

## Still open

- **Should the employee see a line's billability** (read-only)? Not in scope:
  the app shows no billability in Phase 2b, consistent with the brief's
  "the employee is never asked". Revisit after the pilot if people ask.
- Whether a billable-task-without-mapping case should instead be refused at
  save time. Chosen not to, because it blocks the employee over a
  configuration they cannot see or fix.

## Reversibility

The Odoo representation (`so_line` set or not) is unchanged, so lines written
under either model read correctly under the other. Reverting means restoring
the assignment picker; no Odoo data needs migrating back.
