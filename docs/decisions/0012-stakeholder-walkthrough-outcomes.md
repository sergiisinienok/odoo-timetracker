# 0012 — Stakeholder walkthrough of Phase 2b: outcomes

Status: agreed by stakeholders (employees, ops, approvers, owner) in a
walkthrough session on 2026-10-06, before any Phase 2b code. Answers were
recorded live per step in the walkthrough page
(`docs/stakeholder-walkthrough/tasks-walkthrough.html`, published as a
private artifact); the notes below are quoted from it verbatim.

## What was shown

The flow of decision 0011, as one example month at a fictional client, one
question per step. Eight questions; all eight were marked **Agreed**. Six
confirm 0011 unchanged. Two notes change the plan.

## Confirmed unchanged

| Step | Question | Note recorded |
|---|---|---|
| 1 Ops sets up tasks | Right starting tasks (Design, Development, Rework, Ramp-up; Internal: PTO, Bench, Training, Internal work)? Only ops creates tasks? | "The starting task set is fine. Ops is the only team that creates tasks." |
| 2 Logging a day | Pre-fill the task last used on that project? | "Yes" |
| 3 Absorbed work | Will people use Rework / Ramp-up instead of "(unpaid)"? Other names needed? | "those are fine" |
| 5 Old lines | Editing a "No task" line requires a task first (deleting does not)? | "yes" |
| 6 Approver changes a line | Only the approver changes billing on a single line, only in Odoo? | "yes" |
| 8 The invoice | Anything surprising about what reaches the invoice? | "all good" |

Decisions 1, 3, 4, 5, 6, 7, 8 and 9 of 0011 stand as written.

## Changed

### A. The month view shows totals per project only — no per-task breakdown

Step 4 asked whether a per-task breakdown under each project is useful or too
much detail. Note: *"too much details. Keep it simple"*.

- Plan 2b.8 "Month view: totals per project, and per task within it" becomes
  **totals per project**, as today. Legacy lines still show "No task" where
  individual lines are listed (day detail, history).
- Per-task time is still in Odoo (`task_id` on every line) for anyone who
  wants it there. This only removes it from the employee's month view.
- **Interpretation, not stated in the session:** this is read as applying to
  the month totals, the only thing step 4 asked about. Each line still names
  its task where lines are listed, since the employee must be able to see and
  correct which task a line went on. History keeps its task filter (2b.8);
  drop it too if the owner reads "keep it simple" more broadly.

### B. The approver fixes a billable line that had nothing to bill against

Step 7 asked who fixes a line that resolved billable but had no sales order
line to bill against (saved unbillable, reported in the digest). Note:
*"approver will fix it in odoo"*.

- 0011 said "for ops to fix the configuration **or** the approver to set the
  line by hand". Now: **the approver sets the line's Sales Order Item in
  Odoo**, the same action as decision 6 of 0011. Ops may still correct the
  task or project configuration so it stops recurring, but the line itself is
  the approver's.
- The employee is still not blocked and still sees a normal save
  (unchanged from 0011).

## Still open (needs the owner)

- **How the approver hears about it.** The daily digest (step 2.7) goes to
  ops only, and the app has no approver identity: employees and approvers are
  not Odoo users the app reads, and no employee→approver mapping exists in
  `odoo_profile.json`. Options: (a) keep the digest to ops, who pass it on;
  (b) add an approver address (one shared address, or per employee, which
  needs a probe for where Odoo keeps the timesheet approver, e.g.
  `hr.employee.timesheet_manager_id` *(verify)*); (c) the approver finds
  these lines themselves in Odoo before validating. Until decided, 2b.7
  builds the warning and the digest entry as planned, addressed to ops.
- **By when.** Not stated. The natural deadline is before the approver
  validates the month, since the app refuses edits after that.

## Plan changes

- `docs/implementation-plan.md` 2b.8: month view is per-project totals only.
- `docs/implementation-plan.md` risk 15: the approver, not ops, fixes the line.
- `docs/decisions/0011`: unchanged (records stay as accepted); this record
  supersedes the two points above.
