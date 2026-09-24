#!/usr/bin/env python3
"""
Step 2.7 probe: can the integration user create mail.mail, and what are the
fields called? Read-only -- fields_get and check_access_rights only, nothing
is created or sent.

Usage:
    set -a && source .env && set +a
    python3 tools/p2s07-probe_mail_mail.py
"""

import json
import os
import xmlrpc.client

URL = os.environ["ODOO_URL"].rstrip("/")
DB = os.environ["ODOO_DB"]
USER = os.environ["ODOO_USER"]
KEY = os.environ["ODOO_KEY"]

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = common.authenticate(DB, USER, KEY, {})
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")


def call(model, method, *args, **kwargs):
    return models.execute_kw(DB, uid, KEY, model, method, list(args), kwargs)


print(f"uid: {uid}")
for op in ("read", "create", "write", "unlink"):
    try:
        print(f"mail.mail {op}: {call('mail.mail', 'check_access_rights', op, raise_exception=False)}")
    except xmlrpc.client.Fault as exc:
        print(f"mail.mail {op}: FAULT {exc.faultString.splitlines()[-1]}")

wanted = ["subject", "body_html", "email_to", "email_from", "recipient_ids", "auto_delete", "state", "failure_reason"]
try:
    fields = call("mail.mail", "fields_get", wanted, attributes=["type", "string", "required", "readonly"])
    print(json.dumps(fields, indent=2))
except xmlrpc.client.Fault as exc:
    print(f"fields_get FAULT {exc.faultString.splitlines()[-1]}")

# Does the integration user itself have an email address to send from?
try:
    me = call("res.users", "read", [uid], fields=["email", "login"])
    print(f"integration user: {me}")
except xmlrpc.client.Fault as exc:
    print(f"res.users read FAULT {exc.faultString.splitlines()[-1]}")
