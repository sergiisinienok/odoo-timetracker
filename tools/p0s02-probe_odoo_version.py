#!/usr/bin/env python3
"""
Trivial standalone probe: the exact Odoo version string, via common.version().

This hits the /xmlrpc/2/common endpoint, not /xmlrpc/2/object -- it hasn't
shown any of the object-dispatch quirks seen elsewhere on this instance
(has_group() faulting, the malformed-domain ValueError), so it's also a
good quick sanity check that ODOO_URL/ODOO_DB in .env are reachable at all
before running anything heavier.

Usage:
    export ODOO_URL=https://edu-timetracking.odoo.com
    python3 tools/p0s02-probe_odoo_version.py
"""

import json
import os
import xmlrpc.client

URL = os.environ["ODOO_URL"].rstrip("/")

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
info = common.version()

print(json.dumps(info, indent=2))
print(f"\nodoo_version for the profile: {info.get('server_version')!r}")
