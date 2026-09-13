#!/usr/bin/env python3
"""
Support script for step 0.2: create a couple of timesheet lines for a named
employee, one in the previous month and one in the current month, so there's
something real to validate and compare against in the locking spike.

This is a support/setup script, not one of the plan's own named probes -- it
exists to produce test data, not to answer a Phase 0 question by itself.

Usage:
    export ODOO_URL=https://edu-timetracking.odoo.com
    export ODOO_DB=edu-timetracking
    export ODOO_USER=<integration user email>
    export ODOO_KEY=<integration user API key>
    python3 tools/p0s02-probe_create_test_lines.py <employee work email or login>

Prints the id and date of each line it creates. Note the id of the
previous-month line -- that's the one you'll validate in the UI and then
feed into p0s02-probe_validated_line_lock.py.
"""

import datetime
import os
import sys
import xmlrpc.client

if len(sys.argv) != 2:
    sys.exit(f"usage: {sys.argv[0]} <employee work email or login>")

EMPLOYEE_EMAIL = sys.argv[1]

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


# The domain passed here is the domain itself -- [("field", "=", "value")]
# -- not wrapped in an extra list. call()'s own list(args) wrapping already
# handles the one level of nesting execute_kw needs. See
# docs/decisions/0002-domain-argument-convention.md.
emp = call(
    "hr.employee", "search_read",
    [("work_email", "=", EMPLOYEE_EMAIL)],
    fields=["id", "name"],
)
if not emp:
    users = call("res.users", "search_read", [("login", "=", EMPLOYEE_EMAIL)], fields=["id"])
    if users:
        emp = call(
            "hr.employee", "search_read",
            [("user_id", "=", users[0]["id"])],
            fields=["id", "name"],
        )
if not emp:
    sys.exit(f"No employee found for {EMPLOYEE_EMAIL!r} (checked work_email, then user login).")

employee_id = emp[0]["id"]
print(f"Logging time for {emp[0]['name']!r} (employee id {employee_id})")

# 'Internal' project, id 1 -- already has entries from earlier testing.
# Change here if that's not the right project on your instance.
PROJECT_ID = 1

today = datetime.date.today()
this_month = today.replace(day=5)
last_month = (this_month.replace(day=1) - datetime.timedelta(days=1)).replace(day=5)

for d in (last_month, this_month):
    line_id = call(
        "account.analytic.line", "create",
        {
            "employee_id": employee_id,
            "project_id": PROJECT_ID,
            "date": d.isoformat(),
            "unit_amount": 2.0,
            "name": "0.2 locking spike test line",
        },
    )
    print(f"  created line {line_id} on {d.isoformat()}")

print(
    "\nNext: validate the older-month line in the Timesheets UI, then run "
    "p0s02-probe_validated_line_lock.py against its id."
)
