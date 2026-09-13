#!/usr/bin/env python3
"""
Step 0.2, second half: with a line already validated by hand in the
Timesheets UI, confirm by direct experiment -- not assumption -- whether
Odoo actually refuses further writes to it over the API.

This is the part the plan calls out as the one that matters: stock Odoo
marks lines validated but may not make them immutable to the API, in which
case the app itself has to be the enforcement, not a courtesy check.

Usage:
    export ODOO_URL=https://edu-timetracking.odoo.com
    export ODOO_DB=edu-timetracking
    export ODOO_USER=<integration user email>
    export ODOO_KEY=<integration user API key>
    python3 tools/p0s02-probe_validated_line_lock.py <line id>

WARNING: this attempts a write and then an UNLINK (delete) on the given
line. Run it last, after any other test that still needs that line to
exist -- e.g. the readonly_timesheet comparison between two users.
"""

import os
import sys
import xmlrpc.client

if len(sys.argv) != 2:
    sys.exit(f"usage: {sys.argv[0]} <line id>")

LINE_ID = int(sys.argv[1])

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


line = call("account.analytic.line", "read", [LINE_ID], fields=["validated", "unit_amount", "employee_id"])
if not line:
    sys.exit(f"No line with id {LINE_ID}.")
line = line[0]
print("before:", line)
if not line["validated"]:
    sys.exit(f"Line {LINE_ID} is not validated -- wrong id? Validate it in the UI first.")

print("\n--- write test ---")
try:
    call("account.analytic.line", "write", [LINE_ID], {"unit_amount": 9.99})
    after = call("account.analytic.line", "read", [LINE_ID], fields=["unit_amount"])[0]
    print(f"WRITE SUCCEEDED -- unit_amount now {after['unit_amount']}")
    print("=> validated_line_writable: true")
except xmlrpc.client.Fault as e:
    print("WRITE REJECTED")
    print("  ", e.faultString.splitlines()[-1])
    print("=> validated_line_writable: false")

print("\n--- unlink test ---")
try:
    call("account.analytic.line", "unlink", [LINE_ID])
    print("UNLINK SUCCEEDED")
    print("=> validated_line_deletable: true")
except xmlrpc.client.Fault as e:
    print("UNLINK REJECTED")
    print("  ", e.faultString.splitlines()[-1])
    print("=> validated_line_deletable: false")

print(
    "\nRecord both results (validated_line_writable / validated_line_deletable) "
    "in odoo_profile.json."
)
