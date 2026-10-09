# 0013 — Task probe findings: no native task override, no reliable override marker

Status: **open — needs owner decision.** Found by `tools/probe_tasks.py` (step
2b.3), run against the **trial** (`edu-timetracking.odoo.com`) at the owner's
instruction ("implement phase 2b with current .env"). Step 2b.2 (the real
particlesg sandbox) has not been done, so everything here is provisional until
the probe is re-run there. The probe wins (ground rule 5).

## Confirmed as planned

- `project.project.allow_billable` (boolean) exists; Alpha test project True,
  Internal False.
- Open/closed signal: `project.task.is_closed` (non-stored, readable, usable in
  a domain) is True for `state` `1_done` and `1_canceled`. Open domain:
  `[["is_closed","=",False],["active","=",True]]`.
- `account.analytic.line.task_id` exists.
- **The unpaid recipe holds with a task set**: create with `so_line=False`
  stays empty through later `name` and `unit_amount` writes.
  Explicit `so_line=<mapped line>` with a task sticks.
- With no mapping (Internal project), `so_line` stays empty, invoice type
  `non_billable`. No unbillable line moved `qty_delivered`.
- Creating a line with a task and `so_line` unset fills the **employee's mapped
  line**, not the task's own `sale_line_id`.

## Contradictions with the plan

### 1. No native three-valued task billable field

`project.task.allow_billable` is a read-only boolean related to
`project_id.allow_billable`; there is no selection field about billing. Per
2b.3 step 2 this is a **stop-and-ask** before 2b.4: the task-level override
needs a new Studio selection field on `project.task` (*Same as project* /
*Billable* / *Not billable*, default *Same as project*), as assumed in 0011.

### 2. `is_so_line_edited` is not set by an approver-style edit

Setting or clearing `so_line` by a separate `write`, and by `web_save` (the
UI's save method), leaves `is_so_line_edited = False` in both directions. The
real browser form may behave differently (client-side onchange), but nothing
here shows it. Per 2b.3 step 5 this is a **stop**: the app cannot recognise an
override by that marker.

Mitigating, also observed: later `write`s of hours and note did **not** make
Odoo refill or clear `so_line` in either direction. Odoo's own recompute only
re-fires when `task_id`/`project_id` change (changing `task_id` alone on an
unbillable line refilled it with the employee's line). The app can therefore
leave `so_line` alone on hours/note edits without any marker; the marker only
matters for deciding whether a project/task change may re-resolve `so_line`.

## Other finding

Odoo **accepts** a line whose `task_id` belongs to another project, and
silently stores `task_id = False`. The app must validate `task_not_in_project`
itself (already planned).

## Options for the override signal (owner to choose)

- **A. Hand-test in the browser** on the trial: set a line's Sales Order Item in
  the timesheet UI as an approver, then read `is_so_line_edited` over the API.
  If set, the plan stands unchanged.
- **B. Drop the marker.** On hours/note/date edits never write `so_line`
  (proven safe above). On a project/task change, refuse if the line's current
  `so_line` differs from what the rule would have produced at its current
  project/task (i.e. someone changed it), else re-resolve. No new Odoo field.
- **C. Studio flag** the approver ticks (the plan's fallback). One more field
  and one more step for the approver.

## Update: contradiction 1 resolved (owner added the field)

Studio selection `project.task.x_studio_billable` ("Billable?") added on the
trial. Value keys equal their labels: `Same as project`, `Billable`,
`Not billable`. New tasks default to `Same as project`; the 9 pre-existing
tasks read `False` (blank), which the app treats as *Same as project*. The
field is not required and not read-only; the integration user reads and writes
it. `tools/probe_tasks.py` now confirms this and writes the new keys to
`odoo_profile.json` (`task_billable_field`, three value keys, open domain, and
so on). Repeat the field on particlesg in 2b.2 with the same technical name.

Contradiction 2 (override marker) remains open, pending the owner's choice of
A, B or C above. `so_line_manual_marker_reliable` is `false` in the profile.

## Update: contradiction 2 resolved (option A, owner's browser test)

On 2026-10-09 the owner edited two lines by hand in the Odoo timesheet UI
(notes `marker test 1` / `marker test 2`, kept on the trial as fixtures): one
had its Sales Order Item **set** (line 1424), one **cleared** (line 1425).
Both read `is_so_line_edited = True`. App-style `write()` of hours and note
left both `so_line` and the marker unchanged, in both directions. So the UI
sets the marker, plain `write()`/`web_save()` over RPC do not, and lines the
app writes itself stay unmarked — which is exactly what the app needs to tell
an approver's override from its own writes.

The plan stands unchanged (option A). `so_line_manual_marker_reliable` is
`true` in the profile. `probe_tasks.py` section 5e re-checks this against any
lines whose note starts `marker test`; without them it leaves the key alone.
Re-do the hand test on particlesg in 2b.2: the marker is UI behaviour and must
be re-confirmed there.
