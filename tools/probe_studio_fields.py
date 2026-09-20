#!/usr/bin/env python3
"""
Step 0.7 probe -- named by the plan itself in docs/implementation-plan.md's
own Validate text, so this filename stays as-is (no p0sXX prefix).

Confirms the two Studio-added custom fields exist, and round-trips a real
write/read through each.

Fields Studio adds get auto-generated technical names (typically
x_studio_<slug>), not necessarily the literal descriptive names the plan
uses to refer to them ('default_project_field', 'app_entry_id_field') --
this script discovers the real technical names via fields_get rather than
assuming them, consistent with every other probe in this project.

Usage:
    export ODOO_URL=...
    export ODOO_DB=...
    export ODOO_USER=<integration user>
    export ODOO_KEY=<integration user API key>
    python3 tools/probe_studio_fields.py
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


def find_studio_fields(model):
    fields = call(model, "fields_get", [], attributes=["string", "type", "relation"])
    return {n: f for n, f in fields.items() if n.startswith("x_studio_")}


print("=== x_studio_* fields on hr.employee ===")
emp_fields = find_studio_fields("hr.employee")
if not emp_fields:
    print("  (none found -- add the Many2one to project.project via Studio first)")
for name, f in sorted(emp_fields.items()):
    print(f"  {name:35} {f['type']:12} -> {f.get('relation')}  \"{f.get('string')}\"")

print("\n=== x_studio_* fields on account.analytic.line ===")
line_fields = find_studio_fields("account.analytic.line")
if not line_fields:
    print("  (none found -- add the Char field via Studio first)")
for name, f in sorted(line_fields.items()):
    print(f"  {name:35} {f['type']:12} -> {f.get('relation')}  \"{f.get('string')}\"")

# --- Identify which discovered field is which, by type -----------------------
default_project_field = next(
    (n for n, f in emp_fields.items() if f["type"] == "many2one" and f.get("relation") == "project.project"),
    None,
)
app_entry_id_field = next(
    (n for n, f in line_fields.items() if f["type"] == "char"),
    None,
)

print(f"\ndefault_project_field resolved to: {default_project_field!r}")
print(f"app_entry_id_field resolved to: {app_entry_id_field!r}")

if not (default_project_field and app_entry_id_field):
    print(
        "\nOne or both fields not found/not resolvable by type. Add the "
        "missing one(s) via Studio, then re-run before continuing."
    )
    sys.exit(1)

# --- Round-trip test: write then read back, for each field -------------------
print("\n=== round-trip test ===")

emp_before = call("hr.employee", "read", [1], fields=[default_project_field])[0]
print(f"  hr.employee[1].{default_project_field} before: {emp_before[default_project_field]}")
call("hr.employee", "write", [1], {default_project_field: 2})  # project 2, Alpha Inc engagement
emp_after = call("hr.employee", "read", [1], fields=[default_project_field])[0]
print(f"  hr.employee[1].{default_project_field} after write(2): {emp_after[default_project_field]}")
emp_roundtrip_ok = bool(emp_after[default_project_field]) and emp_after[default_project_field][0] == 2
print(f"  round-trip OK: {emp_roundtrip_ok}")
call("hr.employee", "write", [1], {default_project_field: False})
print("  (reset back to empty -- this was a test write, not a real default)")

# For the line field, create a throwaway line rather than touch real data.
line_id = call(
    "account.analytic.line", "create",
    {
        "employee_id": 1,
        "project_id": 1,
        "date": "2026-09-17",
        "unit_amount": 0.0,
        "name": "0.7 studio-field probe",
        app_entry_id_field: "test-entry-abc123",
    },
)
line_after = call("account.analytic.line", "read", [line_id], fields=[app_entry_id_field])[0]
print(f"  account.analytic.line[{line_id}].{app_entry_id_field}: {line_after[app_entry_id_field]!r}")
line_roundtrip_ok = line_after[app_entry_id_field] == "test-entry-abc123"
print(f"  round-trip OK: {line_roundtrip_ok}")
call("account.analytic.line", "unlink", [line_id])
print("  (test line cleaned up)")

print("\n" + "=" * 70)
both_ok = emp_roundtrip_ok and line_roundtrip_ok
print(f"Both Studio fields exist and round-trip cleanly: {both_ok}")
print(f"default_project_field = {default_project_field!r}")
print(f"app_entry_id_field = {app_entry_id_field!r}")
print("=" * 70)
