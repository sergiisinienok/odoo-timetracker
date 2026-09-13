#!/usr/bin/env python3
"""
Step 0.4 probe -- named by the plan itself in docs/implementation-plan.md's
own Validate text, so this filename stays as-is (no p0sXX prefix).

The load-bearing step of Phase 0: confirms two employees can be mapped to
two different sale order lines on the same project (the mechanism the
whole per-employee billing model and the app's assignment-list design rest
on), and resolves an open question from the brief -- where do assignment
validity dates actually live? sale.order.line, sale.order, or neither?
Answered by scanning real field names, not assumed.

Usage:
    export ODOO_URL=...
    export ODOO_DB=...
    export ODOO_USER=<integration user>
    export ODOO_KEY=<integration user API key>
    python3 tools/probe_assignments.py <project id>
"""

import os
import re
import sys
import xmlrpc.client

if len(sys.argv) != 2:
    sys.exit(f"usage: {sys.argv[0]} <project id>")

PROJECT_ID = int(sys.argv[1])

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


# --- 1. Read the project and its employee mapping ---------------------------
proj = call(
    "project.project", "read", [PROJECT_ID],
    fields=["name", "partner_id", "sale_line_id", "sale_line_employee_ids"],
)[0]
print("=== project ===")
print(f"  [{proj['id']}] {proj['name']!r}  customer={proj['partner_id']}")
print(f"  sale_line_id (project-level default line): {proj['sale_line_id']}")
print(f"  sale_line_employee_ids (mapping row ids): {proj['sale_line_employee_ids']}")

if not proj["sale_line_employee_ids"]:
    sys.exit(
        "\nNo employee mapping rows on this project yet -- add them on the "
        "project's Sales/Invoicing tab, then re-run."
    )

# --- 2. Read the actual mapping rows -----------------------------------------
map_fields = call("project.sale.line.employee.map", "fields_get", [], attributes=["string", "type", "relation"])
print("\n=== project.sale.line.employee.map fields ===")
for name in sorted(map_fields):
    f = map_fields[name]
    print(f"  {name:25} {f['type']:12} -> {f.get('relation')}  \"{f.get('string')}\"")

rows = call(
    "project.sale.line.employee.map", "read",
    proj["sale_line_employee_ids"],
    fields=["employee_id", "sale_line_id"],
)
print("\n=== mapping rows ===")
for r in rows:
    print(f"  employee {r['employee_id']} -> sale line {r['sale_line_id']}")

distinct_lines = {r["sale_line_id"][0] for r in rows if r.get("sale_line_id")}
if len(distinct_lines) < 2:
    print(
        "\nWARNING: fewer than 2 distinct sale order lines across the "
        "mapped employees -- this doesn't yet prove two employees can bill "
        "to two different lines on the same project. Add a second mapping "
        "row for a different employee/line before treating 0.4 as done."
    )
else:
    print(
        f"\n{len(rows)} employee(s) mapped to {len(distinct_lines)} distinct "
        "sale order lines. Mechanism confirmed working."
    )

# --- 3. Where do assignment validity dates live? -----------------------------
DATE_INTERESTING = re.compile(r"date|start|end|valid", re.I)

print("\n=== sale.order.line fields matching date/start/end/valid ===")
line_fields = call("sale.order.line", "fields_get", [], attributes=["string", "type"])
line_hits = {n: f for n, f in line_fields.items() if DATE_INTERESTING.search(n)}
for name in sorted(line_hits):
    f = line_hits[name]
    print(f"  {name:30} {f['type']:12} \"{f.get('string')}\"")

print("\n=== sale.order fields matching date/start/end/valid ===")
order_fields = call("sale.order", "fields_get", [], attributes=["string", "type"])
order_hits = {n: f for n, f in order_fields.items() if DATE_INTERESTING.search(n)}
for name in sorted(order_hits):
    f = order_hits[name]
    print(f"  {name:30} {f['type']:12} \"{f.get('string')}\"")

print(
    "\nLook through both lists above for anything meaning 'this line/order "
    "is valid starting/until this date' -- that's where assignment "
    "start/end dates should live. If nothing plausible exists on either "
    "model, that's a real finding: assignment date ranges may need to live "
    "somewhere else entirely (a Studio field, most likely) -- record it "
    "either way, don't leave it unresolved."
)
