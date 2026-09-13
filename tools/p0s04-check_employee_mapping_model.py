#!/usr/bin/env python3
"""
Pre-check for step 0.4, run before any UI setup: does the employee-to-sales-
order-line mapping mechanism (historically the model
project.sale.line.employee.map, exposed via a field on project.project)
still exist on this Odoo 19 instance at all?

Per the plan: if this isn't real, stop and report immediately -- the whole
billing model and the app's assignment-list design rest on it. Don't
improvise a workaround before confirming that's actually necessary.

NOTE: an earlier version of this script also queried ir.model directly to
confirm the mapping model's existence. That model is access-restricted to
users holding the "Access Rights" administration group -- the same
restriction already found on ir.model.data in step 0.1 (see
docs/decisions/0001-odoo19-rpc-quirks.md). Dropped rather than worked
around: fields_get()'s own 'relation' attribute already tells us the
target model for any relational field, which is everything this check
actually needs.

This is a pre-flight check, not the plan's own named 0.4 probe -- once this
confirms the mechanism exists (or reveals what replaced it), the real
tools/probe_assignments.py gets written against a test project + sales
order with employees actually mapped.

Usage:
    export ODOO_URL=...
    export ODOO_DB=...
    export ODOO_USER=<integration user>
    export ODOO_KEY=<integration user API key>
    python3 tools/p0s04-check_employee_mapping_model.py
"""

import os
import re
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


print("=== project.project fields matching sale/employee/line ===")
fields = call("project.project", "fields_get", [], attributes=["string", "type", "relation"])
INTERESTING = re.compile(r"sale.*employee|employee.*sale|sale_line", re.I)
hits = {n: f for n, f in fields.items() if INTERESTING.search(n)}
if not hits:
    print("  (none found by that pattern -- widening to anything with 'sale')")
    hits = {n: f for n, f in fields.items() if "sale" in n.lower()}

for name in sorted(hits):
    f = hits[name]
    print(f"  {name:30} {f['type']:12} -> {f.get('relation')}  \"{f.get('string')}\"")

print(
    "\nLook for a one2many field whose relation is something like "
    "'project.sale.line.employee.map' (or similarly named). If found: the "
    "mechanism is real, proceed with 0.4's UI setup. If nothing plausible "
    "shows up at all: stop here and report back -- this changes the "
    "design, not just a field name."
)
