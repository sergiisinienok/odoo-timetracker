#!/usr/bin/env python3
"""
Investigating whether Odoo's Planning app offers a better home for
assignment validity dates than a Studio field, per the open decision in
docs/decisions/0005-no-assignment-validity-date-field.md.

Checks:
1. Does planning.slot exist at all (is the Planning app installed)?
2. If so, what date-range fields does it have?
3. Does it link to project.project, sale.order.line, or
   project.sale.line.employee.map -- i.e. could it actually connect to the
   billing mechanism we already have, or would it be a second, disconnected
   system?
4. Does project.project or the mapping model have any back-reference to
   planning.slot, suggesting Odoo already wires these together?

Usage:
    export ODOO_URL=...
    export ODOO_DB=...
    export ODOO_USER=<integration user>
    export ODOO_KEY=<integration user API key>
    python3 tools/p0s04-check_planning_app.py
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


# --- 1. Does planning.slot exist? --------------------------------------------
print("=== checking whether planning.slot exists ===")
try:
    fields = call("planning.slot", "fields_get", [], attributes=["string", "type", "relation"])
    print(f"  FOUND -- {len(fields)} fields on planning.slot")
except xmlrpc.client.Fault as e:
    msg = e.faultString.splitlines()[-1]
    print(f"  NOT FOUND (or inaccessible): {msg}")
    print(
        "\nPlanning app doesn't appear to be installed/usable here. "
        "Likely means the Studio-field route (0005) is the answer -- "
        "report back either way."
    )
    sys.exit(0)

# --- 2. Date and link fields on planning.slot --------------------------------
DATE_INTERESTING = re.compile(r"date|start|end", re.I)
LINK_INTERESTING = re.compile(r"project|sale|employee|task", re.I)

print("\n=== planning.slot fields matching date/start/end ===")
for name in sorted(fields):
    if DATE_INTERESTING.search(name):
        f = fields[name]
        print(f"  {name:30} {f['type']:12} -> {f.get('relation')}  \"{f.get('string')}\"")

print("\n=== planning.slot fields matching project/sale/employee/task ===")
for name in sorted(fields):
    if LINK_INTERESTING.search(name):
        f = fields[name]
        print(f"  {name:30} {f['type']:12} -> {f.get('relation')}  \"{f.get('string')}\"")

# --- 3. Does project.project have a back-reference to planning? -------------
print("\n=== project.project fields matching 'planning' ===")
proj_fields = call("project.project", "fields_get", [], attributes=["string", "type", "relation"])
proj_hits = {n: f for n, f in proj_fields.items() if "planning" in n.lower()}
if not proj_hits:
    print("  (none)")
for name in sorted(proj_hits):
    f = proj_hits[name]
    print(f"  {name:30} {f['type']:12} -> {f.get('relation')}  \"{f.get('string')}\"")

# --- 4. Does the mapping model have a back-reference either? ----------------
print("\n=== project.sale.line.employee.map fields matching 'planning' ===")
map_fields = call("project.sale.line.employee.map", "fields_get", [], attributes=["string", "type", "relation"])
map_hits = {n: f for n, f in map_fields.items() if "planning" in n.lower()}
if not map_hits:
    print("  (none)")
for name in sorted(map_hits):
    f = map_hits[name]
    print(f"  {name:30} {f['type']:12} -> {f.get('relation')}  \"{f.get('string')}\"")

print(
    "\nDecide: does planning.slot have both a real date range AND a way to "
    "link back to this specific employee/sale-line/project combination? "
    "If yes, it might genuinely be a better home. If it only has dates but "
    "no natural link to our billing mechanism, that means maintaining two "
    "disconnected systems -- likely not worth it, and 0005's Studio-field "
    "route is probably still the better call."
)
