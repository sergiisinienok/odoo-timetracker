#!/usr/bin/env python3
"""
Step 0.3 probe -- named by the plan itself in docs/implementation-plan.md's
own Validate text, so this filename stays as-is (no p0sXX prefix).

Confirms: role service products exist in both invoicing modes, and a
pricelist returns a different price for the same product under two
different clients.

Field names for product type / invoicing policy / service tracking are NOT
assumed here. Odoo has reworked these repeatedly across versions, and this
project has already been burned twice by guessing Odoo 19 field names (see
docs/decisions/). This script discovers the real field names via
fields_get() first, then reads products and pricelist items using whatever
it actually finds.

Usage:
    export ODOO_URL=...
    export ODOO_DB=...
    export ODOO_USER=<integration user>
    export ODOO_KEY=<integration user API key>
    python3 tools/probe_products.py
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


# --- 1. Discover the real field names on product.template -------------------
PRODUCT_INTERESTING = re.compile(r"polic|track|type|storable|consu|servic", re.I)

fields = call("product.template", "fields_get", [], attributes=["string", "type"])
hits = {n: f for n, f in fields.items() if PRODUCT_INTERESTING.search(n)}

print("=== product.template fields worth knowing about ===")
for name in sorted(hits):
    f = hits[name]
    print(f"  {name:30} {f['type']:12} \"{f.get('string')}\"")

# --- 2. Read every service product -- by type, not by guessing names --------
# An earlier version of this script matched role names via ILIKE, which
# silently missed any product named unlike the four guessed strings (e.g.
# 'Project Manager' contains none of 'Senior Engineer'/'Engineer'/'QA'/'PM').
# Filtering on the confirmed real 'type' field catches every service
# product regardless of naming, and can't go stale as roles get renamed.
probe_fields = ["id", "name"] + sorted(hits.keys())

print("\n=== all service-type products (type == 'service') ===")
products = call("product.template", "search_read", [("type", "=", "service")], fields=probe_fields)
if not products:
    print("  (none found -- create the role products first)")
for p in products:
    print(f"\n  [{p['id']}] {p['name']!r}")
    for k in sorted(hits.keys()):
        v = p.get(k)
        if v not in (False, None, ""):
            print(f"      {k}: {v!r}")

# --- 3. Discover the real field names on product.pricelist.item -------------
ITEM_INTERESTING = re.compile(r"price|percent|pricelist|product", re.I)

item_fields = call("product.pricelist.item", "fields_get", [], attributes=["string", "type"])
item_hits = {n: f for n, f in item_fields.items() if ITEM_INTERESTING.search(n)}

print("\n=== product.pricelist.item fields worth knowing about ===")
for name in sorted(item_hits):
    f = item_hits[name]
    print(f"  {name:30} {f['type']:12} \"{f.get('string')}\"")

# --- 4. For every pricelist, dump its items for the service products found --
print("\n=== pricelists and their service-product items ===")
pricelists = call("product.pricelist", "search_read", [], fields=["id", "name"])
if not pricelists:
    print("  (no pricelists at all -- create the two test-client pricelists first)")

for pl in pricelists:
    print(f"\n  pricelist [{pl['id']}] {pl['name']!r}")
    items = call(
        "product.pricelist.item", "search_read",
        [("pricelist_id", "=", pl["id"])],
        fields=["id"] + sorted(item_hits.keys()),
    )
    if not items:
        print("    (no items)")
    for it in items:
        parts = [f"{k}={it[k]!r}" for k in sorted(item_hits.keys()) if it.get(k) not in (False, None, "")]
        print(f"    item {it['id']}: " + ", ".join(parts))

print(
    "\nEyeball check: pick one service product and compare its price field "
    "across the non-default pricelists above -- it should differ."
)