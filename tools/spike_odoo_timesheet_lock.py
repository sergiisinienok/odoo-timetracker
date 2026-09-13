#!/usr/bin/env python3
"""
Spike: how does Odoo expose timesheet validation / period locking to the API?

Community source shows the hook but not the answer: account.analytic.line has a
computed `readonly_timesheet` field driven by `_is_readonly()`, which returns
False in Community and is "overridden in other timesheet related modules" —
i.e. Enterprise's timesheet_grid. What that override actually sets, and what
fields it adds, can only be seen on a live Enterprise instance.

This script introspects your instance and answers three things:

  1. Which validation/lock-related fields exist on account.analytic.line,
     hr.employee and res.company, and what type they are.
  2. What those fields read as on real timesheet lines.
  3. Whether `readonly_timesheet` is user-relative — it may compute False for
     an approver-privileged user even on a validated line, which would make it
     unsafe as the app's only lock signal.

Usage:
    export ODOO_URL=https://particlesg.odoo.com
    export ODOO_DB=particlesg
    export ODOO_USER=integration@particles.global
    export ODOO_KEY=<API key from Preferences > Account Security>
    python3 spike_odoo_timesheet_lock.py

Best run twice: once as the integration user (timesheet approver rights) and
once as an ordinary employee user. If the readonly flag differs between them on
the same line, the app must read the validation field itself, not readonly_timesheet.
"""

import os
import re
import sys
import xmlrpc.client

URL = os.environ["ODOO_URL"].rstrip("/")
DB = os.environ["ODOO_DB"]
USER = os.environ["ODOO_USER"]
KEY = os.environ["ODOO_KEY"]

INTERESTING = re.compile(r"valid|readonly|lock|approv|closed|frozen", re.I)

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = common.authenticate(DB, USER, KEY, {})
if not uid:
    sys.exit("Authentication failed — check DB name, login, and API key.")
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")


def call(model, method, *args, **kw):
    return models.execute_kw(DB, uid, KEY, model, method, list(args), kw)


print(f"Connected to {URL} as uid={uid} ({USER})\n")

# --- 1. Which groups does this user hold? Decides what it may write. ---------
# has_group() faults over XML-RPC on this instance — see docs/decisions/0001.
# Read membership directly instead: res.users.all_group_ids -> res.groups.
me = call("res.users", "read", [uid], fields=["all_group_ids"])
held = call("res.groups", "read", me[0]["all_group_ids"], fields=["display_name"])
held_names = {g["display_name"] for g in held}

for label in (
    "Timesheets / Administrator",
    "Timesheets / User: all timesheets",
    "Timesheets / User: own timesheets only",
    "Role / User",
):
    print(f"  {label}: {label in held_names}")

print(f"\n  All {len(held_names)} held groups:")
for name in sorted(held_names):
    print(f"    - {name}")

# --- 2. Validation-related fields on the relevant models --------------------
for model in ("account.analytic.line", "hr.employee", "res.company"):
    print(f"\n=== {model} — fields matching {INTERESTING.pattern} ===")
    try:
        fields = call(model, "fields_get", [], attributes=["string", "type", "store", "readonly"])
    except xmlrpc.client.Fault as e:
        print(f"  not readable: {e.faultString}")
        continue
    hits = {n: f for n, f in fields.items() if INTERESTING.search(n)}
    if not hits:
        print("  (none)")
    for name in sorted(hits):
        f = hits[name]
        print(
            f"  {name:38} {f['type']:12} stored={f.get('store')} "
            f"readonly={f.get('readonly')}  \"{f.get('string')}\""
        )

# --- 3. What those fields read as on real timesheet lines -------------------
line_fields = call("account.analytic.line", "fields_get", [], attributes=["type"])
probe = ["id", "date", "employee_id", "project_id", "unit_amount"]
probe += sorted(n for n in line_fields if INTERESTING.search(n))

print(f"\n=== sample timesheet lines, fields: {probe} ===")
lines = call(
    "account.analytic.line",
    "search_read",
    [["project_id", "!=", False]],
    fields=probe,
    limit=10,
    order="date desc",
)
if not lines:
    print("  No timesheet lines found — log a few hours in Odoo first.")
for ln in lines:
    print("  " + "  ".join(f"{k}={ln.get(k)!r}" for k in probe if k in ln))

print(
    "\nWhat to conclude:\n"
    "  * A stored boolean/selection field named like 'validated' is the signal the\n"
    "    app should read to lock a period. Note its exact name.\n"
    "  * If readonly_timesheet is False on a line whose validated field is True,\n"
    "    the flag is relative to THIS user's rights — do not use it as the lock.\n"
    "  * Then confirm the important part by hand: try writing to a validated line\n"
    "    over the API as this user. If Odoo allows it, the app must enforce the\n"
    "    lock itself; stock Odoo marks lines validated but does not make them\n"
    "    immutable to the API."
)
