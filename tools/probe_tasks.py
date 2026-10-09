#!/usr/bin/env python3
"""
Step 2b.3 probe -- named by the plan itself in docs/implementation-plan.md's
Validate text, so this filename stays as-is.

Confirms every Odoo fact Phase 2b needs about tasks and billability:
project billable flag, task open/closed signal, whether anything native could
be a three-valued task override, task_id on the line, the unpaid recipe with
a task set, and whether the approver's manual so_line edit is reliably marked.

Usage:
    export ODOO_URL=... ODOO_DB=... ODOO_USER=... ODOO_KEY=...
    python3 tools/probe_tasks.py [--cleanup]

--cleanup deletes every task and line this run creates.
"""

import json
import os
import sys
from pathlib import Path
import xmlrpc.client

CLEANUP = "--cleanup" in sys.argv

URL = os.environ["ODOO_URL"].rstrip("/")
DB = os.environ["ODOO_DB"]
USER = os.environ["ODOO_USER"]
KEY = os.environ["ODOO_KEY"]

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = common.authenticate(DB, USER, KEY, {})
if not uid:
    sys.exit("Authentication failed -- check DB name, login, and API key.")
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")


def call(model, method, *args, **kw):
    return models.execute_kw(DB, uid, KEY, model, method, list(args), kw)


def one_id(result):
    # create() over XML-RPC on the trial can return [id] (CLAUDE.md quirk).
    return result[0] if isinstance(result, list) else result


# Fixtures (0.4): project 2 with employee 1 mapped to sale order line 1.
PROJECT_ID = 2
EMPLOYEE_ID = 1
MAPPED_SALE_LINE_ID = 1
INTERNAL_PROJECT_ID = int(os.environ.get("INTERNAL_PROJECT_ID", "1"))

LINE = "account.analytic.line"
TASK = "project.task"
created_lines, created_tasks = [], []
decisions = []


def new_task(project_id, name, **extra):
    tid = one_id(call(TASK, "create", {"name": f"2b.3 probe {name}", "project_id": project_id, **extra}))
    created_tasks.append(tid)
    return tid


def new_line(**extra):
    vals = {
        "employee_id": EMPLOYEE_ID,
        "project_id": PROJECT_ID,
        "date": "2026-09-15",
        "unit_amount": 1.0,
        "name": "2b.3 probe",
        **extra,
    }
    lid = one_id(call(LINE, "create", vals))
    created_lines.append(lid)
    return lid


LINE_FIELDS = ["so_line", "task_id", "project_id", "timesheet_invoice_type", "is_so_line_edited"]


def read_line(lid):
    r = call(LINE, "read", [lid], fields=LINE_FIELDS)[0]
    r["so_line"] = r["so_line"][0] if r["so_line"] else False
    return r


def qty(sol_id):
    return call("sale.order.line", "read", [sol_id], fields=["qty_delivered"])[0]["qty_delivered"]


try:
    # --- 1. Project flag ---------------------------------------------------
    print("=== 1. project billable flag ===")
    pf = call("project.project", "fields_get", ["allow_billable"], attributes=["type", "string"])
    print(f"  project.allow_billable: {pf.get('allow_billable')}")
    for pid in (PROJECT_ID, INTERNAL_PROJECT_ID):
        r = call("project.project", "read", [pid], fields=["name", "allow_billable"])[0]
        print(f"  project {pid} {r['name']!r}: allow_billable={r['allow_billable']}")

    # --- 2. Task fields ----------------------------------------------------
    print("\n=== 2. task fields ===")
    tf = call(TASK, "fields_get", [], attributes=["type", "string", "selection", "related", "readonly", "store"])
    for n in ("active", "state", "is_closed", "stage_id", "allow_billable", "sale_line_id"):
        print(f"  {n}: {tf.get(n)}")
    stage_fold = call("project.task.type", "fields_get", ["fold"], attributes=["type"])
    print(f"  project.task.type.fold exists: {'fold' in stage_fold}")
    billable_like = sorted(
        n for n, f in tf.items()
        if f["type"] == "selection" and any(s in n.lower() for s in ("bill", "invoice"))
    )
    print(f"  selection fields about billing/invoice on project.task: {billable_like}")
    ab = tf.get("allow_billable", {})
    print(f"  task.allow_billable: type={ab.get('type')} related={ab.get('related')} readonly={ab.get('readonly')}")
    native_three_valued = bool(billable_like)

    # The Studio override added in 2b.4 (decision 0013): confirm it, read its
    # real value keys, and confirm what new and pre-existing tasks hold.
    BILLABLE_FIELD = "x_studio_billable"
    bf = call(TASK, "fields_get", [BILLABLE_FIELD], attributes=["type", "selection", "readonly"])
    if BILLABLE_FIELD not in bf:
        sys.exit(f"{BILLABLE_FIELD} is missing on project.task -- add it in Studio first (0013).")
    value_keys = [k for k, _label in bf[BILLABLE_FIELD]["selection"]]
    print(f"  {BILLABLE_FIELD}: type={bf[BILLABLE_FIELD]['type']} values={value_keys}")
    if len(value_keys) != 3:
        sys.exit(f"Expected three values on {BILLABLE_FIELD}, got {value_keys}")
    same_key = next(k for k in value_keys if k.lower().startswith("same"))
    yes_key = next(k for k in value_keys if k.lower() == "billable")
    no_key = next(k for k in value_keys if k.lower().startswith("not"))

    open_task = new_task(PROJECT_ID, "open")
    default_val = call(TASK, "read", [open_task], fields=[BILLABLE_FIELD])[0][BILLABLE_FIELD]
    print(f"  new task default for {BILLABLE_FIELD}: {default_val!r}")
    blank = call(TASK, "search_count", [(BILLABLE_FIELD, "=", False), ("id", "not in", created_tasks)])
    print(f"  pre-existing tasks with a blank value (app treats blank as same-as-project): {blank}")
    t_yes = new_task(PROJECT_ID, "billable", **{BILLABLE_FIELD: yes_key})
    t_no = new_task(PROJECT_ID, "not billable", **{BILLABLE_FIELD: no_key})
    rb = {t: call(TASK, "read", [t], fields=[BILLABLE_FIELD])[0][BILLABLE_FIELD] for t in (t_yes, t_no)}
    print(f"  write/read round trip: {rb}")
    done_task = new_task(PROJECT_ID, "done", state="1_done")
    canc_task = new_task(PROJECT_ID, "canceled", state="1_canceled")
    for label, t in (("open", open_task), ("1_done", done_task), ("1_canceled", canc_task)):
        r = call(TASK, "read", [t], fields=["state", "is_closed", "active", "stage_id", "allow_billable"])[0]
        print(f"  {label}: {r}")
    closed_ok = (
        not call(TASK, "read", [open_task], fields=["is_closed"])[0]["is_closed"]
        and call(TASK, "read", [done_task], fields=["is_closed"])[0]["is_closed"]
        and call(TASK, "read", [canc_task], fields=["is_closed"])[0]["is_closed"]
    )
    print(f"  is_closed is False for open, True for done and canceled: {closed_ok}")
    found = call(TASK, "search", [("id", "in", [open_task, done_task, canc_task]), ("is_closed", "=", False)])
    print(f"  domain is_closed=False returns only the open task: {sorted(found) == [open_task]}")
    open_domain = [["is_closed", "=", False], ["active", "=", True]]

    # --- 3. Line field -----------------------------------------------------
    print("\n=== 3. task_id on the line ===")
    lf = call(LINE, "fields_get", ["task_id", "is_so_line_edited"], attributes=["type", "string", "relation"])
    print(f"  {lf}")
    other_project_task = new_task(INTERNAL_PROJECT_ID, "other project")
    try:
        lid = new_line(task_id=other_project_task)
        r = read_line(lid)
        print(f"  task from another project: ACCEPTED by Odoo -> {r}")
        cross_refused = False
    except xmlrpc.client.Fault as e:
        print(f"  task from another project: REFUSED by Odoo -> {str(e.faultString).splitlines()[-1][:160]}")
        cross_refused = True
    decisions.append(f"CROSS-PROJECT TASK REFUSED BY ODOO: {cross_refused}")

    # --- 4. Recompute with a task -----------------------------------------
    print("\n=== 4. recompute with a task ===")
    order_id = call("sale.order.line", "read", [MAPPED_SALE_LINE_ID], fields=["order_id"])[0]["order_id"][0]
    others = call("sale.order.line", "search", [("order_id", "=", order_id), ("id", "!=", MAPPED_SALE_LINE_ID)])
    task_sol = others[0] if others else None
    print(f"  employee's mapped line: {MAPPED_SALE_LINE_ID}; task's different line: {task_sol}")
    if task_sol is None:
        sys.exit("Need a second order line on the test order to tell task vs. employee fills apart.")
    task_w_sol = new_task(PROJECT_ID, "task with sale_line_id", sale_line_id=task_sol)
    print(f"  task sale_line_id readback: {call(TASK, 'read', [task_w_sol], fields=['sale_line_id'])[0]['sale_line_id']}")

    qty_before = {s: qty(s) for s in (MAPPED_SALE_LINE_ID, task_sol)}

    a = read_line(new_line(task_id=task_w_sol))
    print(f"  (a) task set, so_line unset: {a}")
    filled = a["so_line"]
    print(f"      Odoo filled so_line with: {'task line' if filled == task_sol else 'employee line' if filled == MAPPED_SALE_LINE_ID else filled}")

    b_id = new_line(task_id=task_w_sol, so_line=False)
    b0 = read_line(b_id)
    call(LINE, "write", [b_id], {"name": "2b.3 probe renamed"})
    b1 = read_line(b_id)
    call(LINE, "write", [b_id], {"unit_amount": 2.5})
    b2 = read_line(b_id)
    print(f"  (b) task set, so_line=False: create={b0['so_line']} after name={b1['so_line']} after hours={b2['so_line']}")
    recipe_holds = b0["so_line"] is False and b1["so_line"] is False and b2["so_line"] is False
    # Changing the task on an unbillable line (the app re-resolves then, but check Odoo's own behavior)
    call(LINE, "write", [b_id], {"task_id": open_task})
    b3 = read_line(b_id)
    print(f"      after changing task_id alone: so_line={b3['so_line']} (Odoo refill? {bool(b3['so_line'])})")
    decisions.append(
        "UNPAID RECIPE WITH TASK: create() with so_line=False passed explicitly"
        if recipe_holds
        else "UNPAID RECIPE WITH TASK: UNRESOLVED -- so_line refilled; report before 2b.4"
    )

    c = read_line(new_line(task_id=task_w_sol, so_line=MAPPED_SALE_LINE_ID))
    print(f"  (c) task set, so_line=employee's line explicit: {c}")
    explicit_sticks = c["so_line"] == MAPPED_SALE_LINE_ID

    # --- 5. Approver override marker --------------------------------------
    print("\n=== 5. approver override marker ===")
    # 5a: unbillable line, approver SETS so_line by a separate write
    u_id = new_line(task_id=open_task, so_line=False)
    print(f"  5a created unbillable: {read_line(u_id)}")
    call(LINE, "write", [u_id], {"so_line": MAPPED_SALE_LINE_ID})
    u1 = read_line(u_id)
    print(f"     after approver sets so_line: {u1}")
    call(LINE, "write", [u_id], {"unit_amount": 3.0})
    call(LINE, "write", [u_id], {"name": "2b.3 probe app note edit"})
    u2 = read_line(u_id)
    print(f"     after app writes hours+name: {u2}")
    set_survives = u2["so_line"] == MAPPED_SALE_LINE_ID and bool(u2["is_so_line_edited"])
    # 5b: billable line, approver CLEARS so_line
    p_id = new_line(task_id=open_task, so_line=MAPPED_SALE_LINE_ID)
    print(f"  5b created billable: {read_line(p_id)}")
    call(LINE, "write", [p_id], {"so_line": False})
    p1 = read_line(p_id)
    print(f"     after approver clears so_line: {p1}")
    call(LINE, "write", [p_id], {"unit_amount": 3.0})
    call(LINE, "write", [p_id], {"name": "2b.3 probe app note edit"})
    p2 = read_line(p_id)
    print(f"     after app writes hours+name: {p2}")
    clear_survives = p2["so_line"] is False and bool(p2["is_so_line_edited"])
    # 5c: the app's own unbillable write must NOT look like an override
    app_unpaid = read_line(b_id)
    app_marker_clean = not app_unpaid["is_so_line_edited"]
    print(f"  5c app-created unbillable line has marker unset: {app_marker_clean} ({app_unpaid['is_so_line_edited']})")
    print(f"  5d app-created billable line (explicit so_line) marker: {c['is_so_line_edited']}")
    # 5e: lines edited by hand in the Odoo UI (names starting "marker test",
    # created by a human: one with so_line set, one cleared). Plain write()
    # and web_save() never set the marker (5a/5b), the UI does -- so this is
    # the only honest test. The lines are fixtures and are never cleaned up.
    ui_lines = call(LINE, "search_read", [("name", "=like", "marker test%")],
                    fields=["so_line", "is_so_line_edited", "unit_amount", "name"], order="id")
    marker_reliable = None
    if ui_lines:
        ok = True
        for ul in ui_lines:
            before = (ul["so_line"] and ul["so_line"][0], ul["is_so_line_edited"])
            call(LINE, "write", [ul["id"]], {"unit_amount": ul["unit_amount"] + 0.5, "name": ul["name"]})
            call(LINE, "write", [ul["id"]], {"unit_amount": ul["unit_amount"]})
            after = call(LINE, "read", [ul["id"]], fields=["so_line", "is_so_line_edited"])[0]
            after = (after["so_line"] and after["so_line"][0], after["is_so_line_edited"])
            print(f"  5e UI-edited line {ul['id']}: marker={before[1]} so_line={before[0]} -> after app writes {after}")
            ok = ok and before[1] and before == after
        marker_reliable = ok
    else:
        print("  5e no 'marker test' lines found; leaving so_line_manual_marker_reliable unchanged")
    survives = set_survives and clear_survives
    decisions.append(
        f"OVERRIDE MARKER: is_so_line_edited survives app write: {marker_reliable} (UI-edited lines; "
        f"plain write()/web_save() never set it) "
        f"(set direction {set_survives}, clear direction {clear_survives}, "
        f"app-created unbillable unmarked {app_marker_clean}, app-created billable marker {c['is_so_line_edited']})"
    )

    # --- 6. Billable task on an unbillable project, no mapping -----------
    print("\n=== 6. billable task, no mapping (internal project) ===")
    int_task = new_task(INTERNAL_PROJECT_ID, "internal task")
    i_id = new_line(project_id=INTERNAL_PROJECT_ID, task_id=int_task)
    i = read_line(i_id)
    print(f"  {i}")
    decisions.append(
        f"BILLABLE TASK, NO MAPPING: so_line={i['so_line']} invoice_type={i['timesheet_invoice_type']}"
    )

    # --- 7. qty_delivered --------------------------------------------------
    print("\n=== 7. invoice type and qty_delivered ===")
    qty_after = {s: qty(s) for s in qty_before}
    billable_hours = {s: 0.0 for s in qty_before}
    for lid in created_lines:
        r = call(LINE, "read", [lid], fields=["so_line", "unit_amount", "timesheet_invoice_type"])[0]
        print(f"  line {lid}: so_line={r['so_line'] and r['so_line'][0]} hours={r['unit_amount']} type={r['timesheet_invoice_type']}")
        if r["so_line"] and r["so_line"][0] in billable_hours:
            billable_hours[r["so_line"][0]] += r["unit_amount"]
    for s in qty_before:
        print(f"  order line {s}: qty_delivered {qty_before[s]} -> {qty_after[s]} (billable hours written: {billable_hours[s]})")
    qty_ok = all(qty_after[s] - qty_before[s] == billable_hours[s] for s in qty_before)
    decisions.append(f"qty_delivered unchanged: {qty_ok} (only lines with so_line contributed)")

    print("\n" + "=" * 70)
    print(f"PROJECT BILLABLE FIELD: project.allow_billable")
    print(f"TASK OPEN DOMAIN: {open_domain}")
    print(f"NATIVE THREE-VALUED TASK BILLABLE FIELD: {native_three_valued} ({billable_like})")
    print(f"  (task.allow_billable is a {ab.get('type')}, related={ab.get('related')})")
    print(f"EXPLICIT so_line STICKS WITH TASK: {explicit_sticks}")
    print(f"TASK BILLABLE FIELD: {BILLABLE_FIELD} same={same_key!r} billable={yes_key!r} not={no_key!r}")
    for d in decisions:
        print(d)
    print("=" * 70)

    # Merge only this probe's keys into the profile (never hand-edit it).
    profile_path = Path(__file__).resolve().parent.parent / "odoo_profile.json"
    profile = json.loads(profile_path.read_text())
    profile.update({
        "project_billable_field": "allow_billable",
        "task_open_domain": open_domain,
        "task_billable_field": BILLABLE_FIELD,
        "task_billable_same_as_project_value": same_key,
        "task_billable_yes_value": yes_key,
        "task_billable_no_value": no_key,
        "line_task_field": "task_id",
        "so_line_manual_marker_field": "is_so_line_edited",
        **({"so_line_manual_marker_reliable": marker_reliable} if marker_reliable is not None else {}),
        "unpaid_recipe_with_task": "create() with so_line=False passed explicitly" if recipe_holds else None,
    })
    profile_path.write_text(json.dumps(profile, indent=2) + "\n")
    print(f"profile keys written to {profile_path.name}")
finally:
    if CLEANUP:
        print(f"\nCleaning up {len(created_lines)} line(s), {len(created_tasks)} task(s)...")
        if created_lines:
            call(LINE, "unlink", created_lines)
        if created_tasks:
            call(TASK, "unlink", created_tasks)
        print("done.")
    else:
        print(f"\nLeft lines {created_lines}, tasks {created_tasks}. Pass --cleanup to remove.")
