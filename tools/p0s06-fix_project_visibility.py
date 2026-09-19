#!/usr/bin/env python3
"""
Step 0.6 follow-up: project 1 ('Internal') isn't visible in the Odoo UI.
Likely cause: privacy_visibility='portal' with zero followers -- 'portal'
visibility typically requires being a follower to see the project at all,
which is a real access restriction, not just a dashboard display filter.
(is_favorite=False / empty favorite_user_ids is a secondary, separate
cause worth checking in the UI too -- the default Project dashboard is
commonly filtered to starred projects.)

Prints the real selection values for privacy_visibility first (never
assume them). Pass --fix to actually change it to the broadest sensible
internal-facing option; omit it to just look.

Usage:
    export ODOO_URL=...
    export ODOO_DB=...
    export ODOO_USER=<integration user>
    export ODOO_KEY=<integration user API key>
    python3 tools/p0s06-fix_project_visibility.py [--fix]
"""

import os
import sys
import xmlrpc.client

FIX = "--fix" in sys.argv

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


field_info = call("project.project", "fields_get", ["privacy_visibility"], attributes=["selection"])
options = field_info["privacy_visibility"]["selection"]

print("=== valid privacy_visibility options on this instance ===")
for value, label in options:
    print(f"  {value!r}: {label!r}")

if not FIX:
    print(
        "\nRun again with --fix to set project 1's visibility to the "
        "broadest internal option below. Nothing changed yet."
    )
    sys.exit(0)

broadest = next((v for v, _ in options if "employee" in v.lower()), None)
if not broadest:
    broadest = next((v for v, _ in options if v.lower() == "followers"), options[0][0])

print(f"\nSetting project 1's privacy_visibility to {broadest!r}...")
call("project.project", "write", [1], {"privacy_visibility": broadest})

after = call("project.project", "read", [1], fields=["privacy_visibility"])[0]
print(f"after write: {after}")
print(
    "\nStill worth checking in the UI: any 'My Projects' or favorites "
    "filter on the Project app dashboard, separate from this fix."
)
