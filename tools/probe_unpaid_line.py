#!/usr/bin/env python3
"""
Step 0.5 probe -- named by the plan itself in docs/implementation-plan.md's
own Validate text, so this filename stays as-is (no p0sXX prefix).

Determines the exact create/write sequence that produces an "unpaid"
timesheet line -- one with so_line left empty -- that survives Odoo's own
recompute, rather than just appearing empty at read time.

Why this needs a probe at all: the brief describes an unpaid entry as "the
same project, with the sales order line left empty," but Odoo does not
leave it empty on its own -- when a line is created on a project where the
employee has an order-line mapping, so_line is computed and auto-filled.
Making an unpaid line means creating and then explicitly clearing it, and
the clearing has to survive Odoo's recompute logic, not just look right
immediately after the write.

Usage:
    export ODOO_URL=...
    export ODOO_DB=...
    export ODOO_USER=<integration user>
    export ODOO_KEY=<integration user API key>
    python3 tools/probe_unpaid_line.py [--cleanup]

--cleanup deletes every test line this run creates once the experiment is
done. Omit it to leave the lines in Odoo for manual inspection.
"""

import os
import sys
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


# Fixtures from 0.4 -- the Alpha Inc test engagement (project 2), Sergii
# (employee 1) mapped to the Senior Engineer line (sale order line 1).
PROJECT_ID = 2
EMPLOYEE_ID = 1
MAPPED_SALE_LINE_ID = 1

created_line_ids = []


def create_line(**extra):
    vals = {
        "employee_id": EMPLOYEE_ID,
        "project_id": PROJECT_ID,
        "date": "2026-09-15",
        "unit_amount": 1.0,
        "name": "0.5 unpaid-line probe",
    }
    vals.update(extra)
    line_id = call("account.analytic.line", "create", vals)
    created_line_ids.append(line_id)
    return line_id


def read_line(line_id, fields):
    return call("account.analytic.line", "read", [line_id], fields=fields)[0]


# Discover the field names we're not sure exist, rather than assume them.
all_fields = call("account.analytic.line", "fields_get", [], attributes=["type"])

edited_flag = None
for candidate in ("is_so_line_edited", "so_line_manually_set", "is_so_line_manually_set"):
    if candidate in all_fields:
        edited_flag = candidate
        break
print(f"'manually edited' flag on account.analytic.line: {edited_flag!r}")

invoice_type_field = "timesheet_invoice_type" if "timesheet_invoice_type" in all_fields else None
print(f"invoice-type field on account.analytic.line: {invoice_type_field!r}\n")

READ_FIELDS = ["id", "so_line"]
if invoice_type_field:
    READ_FIELDS.append(invoice_type_field)
if edited_flag:
    READ_FIELDS.append(edited_flag)

# Snapshot the mapped order line's delivered qty BEFORE any experiment, so
# step 5 has something real to compare against.
qty_before = call("sale.order.line", "read", [MAPPED_SALE_LINE_ID], fields=["qty_delivered"])[0]["qty_delivered"]
print(f"mapped order line {MAPPED_SALE_LINE_ID} qty_delivered BEFORE: {qty_before}\n")

# --- 1. Create with so_line unset -------------------------------------------
print("=== step 1: create with so_line unset ===")
id1 = create_line()
line1 = read_line(id1, READ_FIELDS)
print(f"  {line1}")
auto_filled = bool(line1.get("so_line"))
print(f"  so_line auto-filled: {auto_filled}\n")

# --- 2. Create with so_line: False passed explicitly ------------------------
print("=== step 2: create with so_line=False explicit ===")
id2 = create_line(so_line=False)
line2 = read_line(id2, READ_FIELDS)
print(f"  {line2}")
stayed_empty_on_create = not bool(line2.get("so_line"))
print(f"  so_line stayed empty on create: {stayed_empty_on_create}\n")

# --- 3. Clear an auto-filled line, then trigger a recompute -----------------
print("=== step 3: clear an auto-filled line, then trigger a recompute ===")
id3 = create_line()
print(f"  after create (auto-filled): {read_line(id3, READ_FIELDS)}")
call("account.analytic.line", "write", [id3], {"so_line": False})
print(f"  after explicit clear: {read_line(id3, READ_FIELDS)}")
call("account.analytic.line", "write", [id3], {"name": "0.5 unpaid-line probe (renamed)"})
after_unrelated_write = read_line(id3, READ_FIELDS)
print(f"  after unrelated write (name): {after_unrelated_write}")
refilled = bool(after_unrelated_write.get("so_line"))
print(f"  so_line refilled by recompute: {refilled}\n")

# --- 4. Same as 3, but also set the 'edited' flag if one exists -------------
id4 = None
refilled_flagged = None
if edited_flag:
    print(f"=== step 4: same as step 3, but also set {edited_flag}=True ===")
    id4 = create_line()
    call("account.analytic.line", "write", [id4], {"so_line": False, edited_flag: True})
    print(f"  after clear + flag: {read_line(id4, READ_FIELDS)}")
    call("account.analytic.line", "write", [id4], {"name": "0.5 unpaid-line probe (renamed, flagged)"})
    after_flagged = read_line(id4, READ_FIELDS)
    print(f"  after unrelated write: {after_flagged}")
    refilled_flagged = bool(after_flagged.get("so_line"))
    print(f"  so_line refilled with flag set: {refilled_flagged}\n")
else:
    print("=== step 4: skipped -- no 'edited' flag field found on this instance ===\n")

# --- 5. Confirm unpaid hours don't leak into the mapped line's delivered qty -
print("=== step 5: confirm unpaid hours don't reach the mapped order line's delivered qty ===")
qty_after = call("sale.order.line", "read", [MAPPED_SALE_LINE_ID], fields=["qty_delivered"])[0]["qty_delivered"]
print(f"  mapped order line {MAPPED_SALE_LINE_ID} qty_delivered AFTER: {qty_after}")

# Step 1's line (id1) is deliberately left auto-filled/paid for the whole
# run, to observe the auto-fill behaviour -- it legitimately contributes its
# own hours to qty_delivered. So the right check isn't "unchanged" -- it's
# "increased by exactly the still-paid line's hours, and nothing more" (i.e.
# the unpaid lines 2/3/4 contribute zero on top of that).
paid_line = read_line(id1, ["unit_amount", "so_line"])
expected_delta = paid_line["unit_amount"] if paid_line.get("so_line") else 0.0
actual_delta = qty_after - qty_before
unpaid_lines_dont_leak = (actual_delta == expected_delta)
print(f"  expected delta (only the still-paid step-1 line's hours): {expected_delta}")
print(f"  actual delta: {actual_delta}")
print(f"  unpaid lines contribute nothing extra: {unpaid_lines_dont_leak}\n")

for lid in (id2, id3, id4):
    if lid is None:
        continue
    line = read_line(lid, READ_FIELDS)
    print(f"  line {lid}: so_line={line.get('so_line')}, {invoice_type_field}={line.get(invoice_type_field)}")

# --- Decision -----------------------------------------------------------------
print("\n" + "=" * 70)
if not auto_filled:
    recipe = "create() with so_line omitted -- it is never auto-filled on this instance"
elif stayed_empty_on_create:
    recipe = "create() with so_line=False passed explicitly"
elif not refilled:
    recipe = "create() (auto-filled), then write({'so_line': False}) -- survives a later unrelated write"
elif edited_flag and refilled_flagged is False:
    recipe = f"create() (auto-filled), then write({{'so_line': False, '{edited_flag}': True}}) -- the flag is required for it to stick"
else:
    recipe = "UNRESOLVED -- so_line was refilled by the recompute in every attempt tried. Report before writing dependent code."

print(f"UNPAID RECIPE: {recipe}")
print(f"unpaid lines contribute nothing extra: {unpaid_lines_dont_leak}")
print("=" * 70)

# --- Cleanup ------------------------------------------------------------------
if CLEANUP:
    print(f"\nCleaning up {len(created_line_ids)} test line(s)...")
    call("account.analytic.line", "unlink", created_line_ids)
    print("done.")
else:
    print(f"\n{len(created_line_ids)} test line(s) left in Odoo (ids: {created_line_ids}). Pass --cleanup to remove them.")
