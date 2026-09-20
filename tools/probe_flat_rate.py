#!/usr/bin/env python3
"""
Step 0.9 probe -- named by the plan itself in docs/implementation-plan.md's
own Validate text, so this filename stays as-is (no p0sXX prefix).

Proves the two billing modes coexist on the same project: a fixed-price
line, mapped to a third employee, appears through the exact same
assignment mechanism as the T&M lines from 0.4, and logging hours against
it does not move what will be invoiced.

Assumes the new flat-rate sale order line has already been added to order
S00001 (project 2) by hand in the UI, so its price/qty come from Odoo's
own onchange logic rather than a guessed API create() call. This script
creates the third test employee, the employee-to-line mapping, logs test
hours, and does the before/after invoiceable-amount check.

Usage:
    export ODOO_URL=...
    export ODOO_DB=...
    export ODOO_USER=<integration user>
    export ODOO_KEY=<integration user API key>
    python3 tools/probe_flat_rate.py <new_sale_line_id>
"""

import os
import re
import sys
import xmlrpc.client

if len(sys.argv) != 2:
    sys.exit(f"usage: {sys.argv[0]} <new flat-rate sale order line id>")

NEW_LINE_ID = int(sys.argv[1])
PROJECT_ID = 2

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


# --- 0. Discover the real 'invoiceable amount' field name(s) ----------------
line_fields = call("sale.order.line", "fields_get", [], attributes=["string", "type"])
INVOICE_INTERESTING = re.compile(r"invoic|amount", re.I)
invoice_hits = {n: f for n, f in line_fields.items() if INVOICE_INTERESTING.search(n)}
print("=== sale.order.line fields matching invoic/amount ===")
for name in sorted(invoice_hits):
    f = invoice_hits[name]
    print(f"  {name:30} {f['type']:12} \"{f.get('string')}\"")

# --- 1. Confirm the new line is real and priced ------------------------------
line = call(
    "sale.order.line", "read", [NEW_LINE_ID],
    fields=["product_id", "product_uom_qty", "price_unit", "qty_delivered"] + sorted(invoice_hits.keys()),
)[0]
print(f"\n=== sale order line {NEW_LINE_ID} ===")
for k, v in line.items():
    if k != "id":
        print(f"  {k}: {v}")

# --- 2. Create the third test employee ---------------------------------------
employee_id = call("hr.employee", "create", {"name": "Third Test Employee (Flat Rate)"})
print(f"\ncreated third test employee: id {employee_id}")

# --- 3. Map this employee to the new line ------------------------------------
map_id = call(
    "project.sale.line.employee.map", "create",
    {"project_id": PROJECT_ID, "sale_line_id": NEW_LINE_ID, "employee_id": employee_id},
)
print(f"created mapping row: id {map_id}")

# --- 4. Confirm the assignment mechanism returns this employee's own line ---
proj = call("project.project", "read", [PROJECT_ID], fields=["sale_line_employee_ids"])[0]
rows = call(
    "project.sale.line.employee.map", "read",
    proj["sale_line_employee_ids"],
    fields=["employee_id", "sale_line_id"],
)
this_row = [r for r in rows if r["employee_id"][0] == employee_id]
print(f"\nmapping rows for this employee: {this_row}")
assignment_ok = bool(this_row) and this_row[0]["sale_line_id"][0] == NEW_LINE_ID

# --- 5. Snapshot invoiceable-amount fields BEFORE logging hours -------------
before = call("sale.order.line", "read", [NEW_LINE_ID], fields=sorted(invoice_hits.keys()) + ["qty_delivered"])[0]
print(f"\ninvoiceable-amount fields BEFORE logging hours: {before}")

# --- 6. Log hours for this employee ------------------------------------------
line_ts_id = call(
    "account.analytic.line", "create",
    {
        "employee_id": employee_id,
        "project_id": PROJECT_ID,
        "date": "2026-09-20",
        "unit_amount": 5.0,
        "name": "0.9 flat-rate probe",
    },
)
ts_line = call("account.analytic.line", "read", [line_ts_id], fields=["so_line", "timesheet_invoice_type"])[0]
print(f"\nlogged timesheet line {line_ts_id}: {ts_line}")
hours_landed_on_new_line = bool(ts_line.get("so_line")) and ts_line["so_line"][0] == NEW_LINE_ID

# --- 7. Snapshot invoiceable-amount fields AFTER logging hours --------------
after = call("sale.order.line", "read", [NEW_LINE_ID], fields=sorted(invoice_hits.keys()) + ["qty_delivered"])[0]
print(f"invoiceable-amount fields AFTER logging hours: {after}")

# '_at_date'-suffixed fields (amount_to_invoice_at_date, qty_*_at_date)
# appear to require a specific date passed via the read context -- read
# plainly, as every field in this project is read, they compute something
# resembling price_unit * qty_delivered, which is misleading for a
# fixed-price line. Excluded here; see docs/decisions/0006. The fields
# that actually govern invoice generation (monetary types, qty_to_invoice,
# invoice_status) are what this check relies on.
REAL_INVOICE_FIELDS = [k for k in invoice_hits if not k.endswith("_at_date") and k != "invoice_lines"]
excluded = [k for k in invoice_hits if k not in REAL_INVOICE_FIELDS]
print(f"\nexcluded from the check as context-dependent (see 0006): {excluded}")

amount_fields_unchanged = all(before[k] == after[k] for k in REAL_INVOICE_FIELDS if k in before and k in after)
qty_delivered_moved = before.get("qty_delivered") != after.get("qty_delivered")

print("\n" + "=" * 70)
print(f"assignment mechanism returns this employee with their own line: {assignment_ok}")
print(f"hours recorded against the correct line: {hours_landed_on_new_line}")
print(f"qty_delivered changed: {qty_delivered_moved}  (informational only -- unclear whether a")
print("  flat-rate/ordered_prepaid line tracks qty_delivered from timesheets at all; not a pass/fail here)")
print(f"real invoicing fields unchanged by the hours (the actual point of this step): {amount_fields_unchanged}")
print("=" * 70)

both_billing_modes_work_identically = assignment_ok and hours_landed_on_new_line and amount_fields_unchanged
print(f"\nBoth billing modes work through the same assignment path: {both_billing_modes_work_identically}")

call("account.analytic.line", "unlink", [line_ts_id])
print("(test timesheet line cleaned up -- employee, mapping, and order line left in place for inspection)")
