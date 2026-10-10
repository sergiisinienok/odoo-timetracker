#!/usr/bin/env python3
"""
Step 2b.4 check: list every task on every project with the billability the
app will resolve for one employee, so a human can eyeball it against the
setup list in docs/implementation-plan.md (2b.4).

Uses the app's own resolve_billing (api/src), the profile for every Odoo
name, and the employee's project.sale.line.employee.map rows. Read-only.

Usage:
    export ODOO_URL=... ODOO_DB=... ODOO_USER=... ODOO_KEY=...
    python3 tools/p2bs04-check_task_setup.py [employee_id]   # default 1
"""

import json
import os
import sys
import xmlrpc.client
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api" / "src"))
from tti.domain.billing import TaskOverride, resolve_billing  # noqa: E402

profile = json.loads((ROOT / "odoo_profile.json").read_text())
EMPLOYEE_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1

URL, DB = os.environ["ODOO_URL"].rstrip("/"), os.environ["ODOO_DB"]
USER, KEY = os.environ["ODOO_USER"], os.environ["ODOO_KEY"]
uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, USER, KEY, {})
if not uid:
    sys.exit("Authentication failed.")
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")


def call(model, method, *args, **kw):
    return models.execute_kw(DB, uid, KEY, model, method, list(args), kw)


# The Odoo boundary: raw selection value -> TaskOverride. Blank (tasks that
# predate the field) means same-as-project.
OVERRIDES = {
    profile["task_billable_yes_value"]: TaskOverride.BILLABLE,
    profile["task_billable_no_value"]: TaskOverride.NOT_BILLABLE,
    profile["task_billable_same_as_project_value"]: TaskOverride.SAME_AS_PROJECT,
}
bfield, pfield = profile["task_billable_field"], profile["project_billable_field"]

mapped = {
    m["project_id"][0]: m["sale_line_id"][0]
    for m in call("project.sale.line.employee.map", "search_read",
                  [("employee_id", "=", EMPLOYEE_ID)], fields=["project_id", "sale_line_id"])
}
projects = call("project.project", "search_read", [], fields=["name", pfield], order="id")
tasks = call("project.task", "search_read", [("project_id", "!=", False)],
             fields=["name", "project_id", bfield, "is_closed", "active"], order="project_id, id")

print(f"employee {EMPLOYEE_ID}; mapped order line per project: {mapped}\n")
for p in projects:
    pid = p["id"]
    print(f"project {pid} {p['name']!r}: billable default={p[pfield]}, "
          f"employee's order line={mapped.get(pid)}")
    for t in (t for t in tasks if t["project_id"][0] == pid):
        override = OVERRIDES[t[bfield] or profile["task_billable_same_as_project_value"]]
        so_line, warning = resolve_billing(p[pfield], override, mapped.get(pid))
        state = "CLOSED" if t["is_closed"] else "open  "
        result = "BILLABLE" if so_line else "unbillable"
        print(f"    task {t['id']:>3} {state} {t['name']!r:42} override={t[bfield] or '(blank)':16}"
              f" -> {result}{'  WARNING ' + warning if warning else ''}")
