# 0014 — Every unbillable project is open to every employee; no special internal project

Status: accepted by owner 2026-10-10, after Phase 2b step 2b.8. Changes decisions
of 0011 about *which projects an employee can log against*; everything about
billing, tasks and approver overrides in 0011 and 0012 stands.

## What changes

An employee's project list is now:

1. **Every project they are mapped to** in `project.sale.line.employee.map`
   (the billable client engagements) — unchanged, with every open task and the
   same billing resolution; and
2. **Every active project that is unbillable** (`allow_billable` false) **and
   allows timesheets** (`allow_timesheets` true), whether or not they are mapped
   to it, each with **all its open tasks**.

A billable project the employee has no mapping on is still not available
(`project_not_held`): billing needs their order line.

**The "internal project" is abandoned.** `INTERNAL_PROJECT_ID`, the "Internal"
label and the idea of one catch-all project are gone. An unbillable project is
chosen by its own project name, like any other, and ops makes as many as they
want (internal work, bench, PTO, pre-sales …), each with its own tasks. A
mapped-and-unbillable project is also named by the project, not its customer.
Billable projects keep the client-name labels of 0011 (project name appended
when one client has two).

Ordering in the picker: mapped projects first (by id), then the other
unbillable projects by name.

## Considered and dropped: filtering unbillable tasks by assignee

The owner first asked for unbillable-project tasks to be filtered by task
assignee. Probing the trial showed the premise in 0011 decision 3 ("employees
have no Odoo users") does not hold there: four of five employees have
`hr.employee.user_id`, and `project.task.user_ids` holds the assignees, so the
match is native. It was dropped in favour of **showing every open task on every
unbillable project**. If it comes back: employees without a linked user (employee
3 on the trial) would see no tasks at all, and particlesg has not been checked.

## What this does not change

- Billing: an unbillable project defaults to unbillable; a task marked *Billable*
  on it resolves billable only if the employee happens to be mapped on that
  project, otherwise it is saved unbillable with `billable_without_order_line`
  and reported in the digest (0011 assumption 2, 0012).
- Editing an unmoved line stays allowed after its task closes.

## Consequences

- **Every employee sees every unbillable project's name and tasks.** Anything
  confidential should not be set up as an unbillable project.
- **The picker grows with ops' unbillable projects**, and unbillable projects
  with no open task are listed empty ("no open tasks yet") rather than hidden.
- The daily digest's "projects with no open task" now covers mapped projects only.
- On the trial, the original project 1 "Internal" (blank Training and Meeting
  tasks) and project 33 "Internal project (not billable, no mapping)" are now two
  ordinary unbillable projects. Archive the one ops does not want.
- Requires the profile key `project_timesheets_field` (probed in 2b.3's
  `probe_tasks.py`, section 6b).

## Reversibility

Only the catalog's project query changes; entries, billing and the outbox are
untouched. Restoring a single internal project means re-adding the config value
and the label.

## Brief

Amended in place to v9: the "Internal" kind, the project-list sentence of the
entry fields, the Odoo-fields row and the "one catch-all internal project"
decision.

## Addendum (2026-10-10): Odoo's own "Internal" project stays hidden

Odoo ships one built-in company "Internal" project (`project.project.is_internal_project`
true; the trial's id 1, linked from `res.company.internal_project_id`) and hides it in
its own UI. Listing every unbillable project made it appear in the app's picker, which
Odoo's UI does not show. The catalog now leaves out projects with `is_internal_project`
set, so the two agree. Profile key `project_internal_field` (probed in `probe_tasks.py`,
section 6b). This is Odoo's flag, not the config value abandoned above: ops' own
unbillable projects are all listed. Lines already logged on it still show in the month
view and history.
