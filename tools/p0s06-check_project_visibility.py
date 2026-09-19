#!/usr/bin/env python3
"""
Diagnosing why project id 1 ('Internal') doesn't appear in the Odoo UI's
Project app, despite existing and reading back cleanly over the API in
step 0.6. Checks the usual causes: archived (active=False), wrong
company, and restricted visibility/privacy/membership settings.

Ad-hoc diagnostic, not one of the plan's own named probes -- p0sXX
prefixed per the established convention.

Usage:
    export ODOO_URL=...
    export ODOO_DB=...
    export ODOO_USER=<integration user>
    export ODOO_KEY=<integration user API key>
    python3 tools/p0s06-check_project_visibility.py
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


fields = call("project.project", "fields_get", [], attributes=["string", "type", "relation"])
INTERESTING = re.compile(r"active|company|visib|privacy|favorite|member|follower|user_id|access", re.I)
hits = {n: f for n, f in fields.items() if INTERESTING.search(n)}

print("=== project.project fields matching active/company/visibility/member/access ===")
for name in sorted(hits):
    f = hits[name]
    print(f"  {name:30} {f['type']:12} -> {f.get('relation')}  \"{f.get('string')}\"")

# read() bypasses the active_test domain filter that list/search views
# apply by default -- so this will succeed even if the project is archived,
# which is exactly what we want to check for.
proj = call("project.project", "read", [1], fields=["name"] + sorted(hits.keys()))[0]
print("\n=== project 1 values ===")
for k, v in proj.items():
    print(f"  {k}: {v}")

if "active" in proj and proj["active"] is False:
    print("\n>>> FOUND IT: active=False -- the project is archived. Default UI views hide")
    print(">>> archived records. In Odoo: open the Project app, remove/clear any search")
    print(">>> filters, then look under Filters -> Archived (or the equivalent toggle)")
    print(">>> to find and unarchive it.")
