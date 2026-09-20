#!/usr/bin/env python3
"""
Step 0.8 probe -- named by the plan itself in docs/implementation-plan.md's
own Validate text, so this filename stays as-is (no p0sXX prefix).

Formal, standalone proof that the integration user can create, update, and
delete timesheet lines belonging to employees other than itself -- the
design-critical assumption the whole write-through app depends on: one
login, writing on behalf of everyone. Already exercised in passing across
0.2's and 0.5's test-data scripts (both employees 1 and 2 have had lines
created/written/deleted by this same login throughout Phase 0); this
script is the plan's own explicit six-operation proof, in one place.

Usage:
    export ODOO_URL=...
    export ODOO_DB=...
    export ODOO_USER=<integration user>
    export ODOO_KEY=<integration user API key>
    python3 tools/probe_write_other_employee.py
"""

import os
import sys
import xmlrpc.client

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


EMPLOYEES = [
    (1, "Sergii Sinienok"),
    (2, "Polina Employee Test"),
]
# 'Internal' -- non-billable, no side effects on real sale-order numbers or
# the so_line auto-fill behaviour from 0.5. This proof is about access
# rights only, so the simplest possible project keeps it uncontaminated by
# billing mechanics.
PROJECT_ID = 1

results = []

for emp_id, emp_name in EMPLOYEES:
    print(f"=== employee {emp_id} ({emp_name}) ===")
    ok = {"create": False, "update": False, "delete": False}

    try:
        line_id = call(
            "account.analytic.line", "create",
            {
                "employee_id": emp_id,
                "project_id": PROJECT_ID,
                "date": "2026-09-20",
                "unit_amount": 1.0,
                "name": "0.8 write-on-behalf-of probe",
            },
        )
        print(f"  CREATE ok -- line {line_id}")
        ok["create"] = True
    except xmlrpc.client.Fault as e:
        print(f"  CREATE FAILED: {e.faultString.splitlines()[-1]}")
        results.append((emp_id, ok))
        print()
        continue

    try:
        call("account.analytic.line", "write", [line_id], {"unit_amount": 2.0})
        after = call("account.analytic.line", "read", [line_id], fields=["unit_amount"])[0]
        print(f"  UPDATE ok -- unit_amount now {after['unit_amount']}")
        ok["update"] = True
    except xmlrpc.client.Fault as e:
        print(f"  UPDATE FAILED: {e.faultString.splitlines()[-1]}")

    try:
        call("account.analytic.line", "unlink", [line_id])
        print("  DELETE ok")
        ok["delete"] = True
    except xmlrpc.client.Fault as e:
        print(f"  DELETE FAILED: {e.faultString.splitlines()[-1]}")

    results.append((emp_id, ok))
    print()

print("=" * 70)
all_ok = all(all(ok.values()) for _, ok in results)
for emp_id, ok in results:
    status = "PASS" if all(ok.values()) else "FAIL"
    print(f"employee {emp_id}: {status} -- {ok}")
print(f"\nAll 6 operations (create/update/delete x 2 employees) succeeded: {all_ok}")
print("=" * 70)
