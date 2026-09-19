#!/usr/bin/env python3
"""
Step 0.6 probe -- named by the plan itself in docs/implementation-plan.md's
own Validate text, so this filename stays as-is (no p0sXX prefix).

Confirms the internal (non-billable) project is correctly unreachable by
any sales order: no employee mapping, and any timesheet line logged there
lands with an empty so_line and a non-billable invoice type.

Usage:
    export ODOO_URL=...
    export ODOO_DB=...
    export ODOO_USER=<integration user>
    export ODOO_KEY=<integration user API key>
    python3 tools/probe_internal_project.py [project_id]

Defaults to project id 1 ('Internal'), the pre-existing project already
used for non-billable entries throughout Phase 0 -- reused here rather
than creating a redundant second one, pending this probe confirming it's
actually configured billable=false with no sales order, not just named
'Internal'. Pass a different id to check some other project instead.
"""

import os
import re
import sys
import xmlrpc.client

PROJECT_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1

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


# --- 1. Discover the real 'billable' field name on project.project ----------
fields = call("project.project", "fields_get", [], attributes=["string", "type"])
BILLABLE_INTERESTING = re.compile(r"bill|invoic", re.I)
billable_hits = {n: f for n, f in fields.items() if BILLABLE_INTERESTING.search(n)}

print("=== project.project fields matching bill/invoic ===")
for name in sorted(billable_hits):
    f = billable_hits[name]
    print(f"  {name:30} {f['type']:12} \"{f.get('string')}\"")

# --- 2. Read the project itself ----------------------------------------------
proj_fields = ["id", "name", "partner_id", "sale_line_id", "sale_line_employee_ids"] + sorted(billable_hits.keys())
proj = call("project.project", "read", [PROJECT_ID], fields=proj_fields)[0]

print(f"\n=== project [{proj['id']}] {proj['name']!r} ===")
for k in proj_fields[1:]:
    print(f"  {k}: {proj.get(k)}")

no_customer = not proj.get("partner_id")
no_sale_line = not proj.get("sale_line_id")
no_mapping = not proj.get("sale_line_employee_ids")

print(f"\n  no customer set: {no_customer}")
print(f"  no project-level sale line: {no_sale_line}")
print(f"  no employee mapping rows: {no_mapping}")

# --- 3. Create a fresh line on it and confirm it lands non-billable ---------
print(f"\n=== creating a fresh line on project {PROJECT_ID} ===")
line_id = call(
    "account.analytic.line", "create",
    {
        "employee_id": 1,
        "project_id": PROJECT_ID,
        "date": "2026-09-16",
        "unit_amount": 1.0,
        "name": "0.6 internal-project probe",
    },
)
line = call(
    "account.analytic.line", "read", [line_id],
    fields=["so_line", "timesheet_invoice_type"],
)[0]
print(f"  {line}")

so_line_empty = not line.get("so_line")
non_billable = line.get("timesheet_invoice_type") == "non_billable"
print(f"\n  so_line empty: {so_line_empty}")
print(f"  timesheet_invoice_type == 'non_billable': {non_billable}")

call("account.analytic.line", "unlink", [line_id])
print("  (test line cleaned up)")

# --- Decision -----------------------------------------------------------------
print("\n" + "=" * 70)
provably_unreachable = no_sale_line and no_mapping and so_line_empty and non_billable
print(f"Internal project provably unreachable by any sales order: {provably_unreachable}")
print("=" * 70)

if not provably_unreachable:
    print(
        "\nNot yet clean -- check the failing condition(s) above before "
        "treating 0.6 as done. If this project has a customer/sale line "
        "set, either clear it in the UI or point this script at a "
        "different, genuinely internal project id."
    )
