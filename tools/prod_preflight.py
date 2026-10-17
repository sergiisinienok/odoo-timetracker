#!/usr/bin/env python3
"""
Production preflight: does the Odoo instance in .env have everything
odoo_profile.json says it has, and is the integration user provisioned the way
the app needs? READ-ONLY -- authenticate, fields_get, read, search_read,
check_access_rights. Nothing is created, written or deleted, so it is safe to
run against production (ground rule 3 is about writes).

Every Odoo name comes from the profile (ground rule 2); this script only maps
each profile key to the model it lives on. A key the profile has that the
instance lacks is a FAIL. The exit code is non-zero if any check FAILs, so a
deploy script can gate on it. WARN means "look at this", not "stop".

Usage:
    set -a && source .env && set +a
    python3 tools/prod_preflight.py
    python3 tools/prod_preflight.py --profile path/to/odoo_profile.json
"""

import argparse
import json
import os
import sys
import xmlrpc.client
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# profile key -> (model, expected field type or None, expected relation or None)
PROFILE_FIELDS = {
    "validation_field": ("account.analytic.line", None, None),
    "employee_validated_through": ("hr.employee", "date", None),
    "default_project_field": ("hr.employee", "many2one", "project.project"),
    "app_entry_id_field": ("account.analytic.line", "char", None),
    "line_task_field": ("account.analytic.line", "many2one", "project.task"),
    "so_line_manual_marker_field": ("account.analytic.line", "boolean", None),
    "project_billable_field": ("project.project", "boolean", None),
    "project_timesheets_field": ("project.project", "boolean", None),
    "project_internal_field": ("project.project", "boolean", None),
    "task_billable_field": ("project.task", "selection", None),
    "product_type_field": ("product.template", None, None),
    "invoice_policy_field": ("product.template", None, None),
}

# Fields the app searches on, so they must be stored. The rest are only read,
# and some (project_internal_field) are computed and legitimately unstored.
MUST_BE_STORED = {"app_entry_id_field"}

results: list[tuple[str, str, str]] = []


def record(level: str, name: str, detail: str = "") -> None:
    results.append((level, name, detail))
    print(f"{level:<5} {name}" + (f" -- {detail}" if detail else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", default=str(ROOT / "odoo_profile.json"))
    args = parser.parse_args()

    for var in ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_KEY"):
        if not os.environ.get(var):
            sys.exit(f"{var} is not set -- source .env first.")
    url, db = os.environ["ODOO_URL"].rstrip("/"), os.environ["ODOO_DB"]
    user, key = os.environ["ODOO_USER"], os.environ["ODOO_KEY"]
    domain = os.environ.get("GOOGLE_HOSTED_DOMAIN", "")
    profile = json.loads(Path(args.profile).read_text())

    print(f"Target: {url}  db={db}  user={user}\nProfile: {args.profile}\n")

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    try:
        version = common.version()["server_version"]
        uid = common.authenticate(db, user, key, {})
    except Exception as exc:  # noqa: BLE001 -- any transport failure is a FAIL here
        record("FAIL", "connect", str(exc))
        return 1
    if not uid:
        record("FAIL", "authenticate", "bare Access Denied: wrong db/login, or the API key is wrong/expired")
        return 1
    record("PASS", "authenticate", f"uid={uid}")

    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def call(model, method, *a, **kw):
        return models.execute_kw(db, uid, key, model, method, list(a), kw)

    # -- version ----------------------------------------------------------
    if version == profile.get("odoo_version"):
        record("PASS", "odoo version matches profile", version)
    else:
        record("FAIL", "odoo version matches profile", f"instance {version!r}, profile {profile.get('odoo_version')!r}")

    # -- the integration user ---------------------------------------------
    me = call("res.users", "read", [uid], fields=["all_group_ids"])
    held = sorted(g["display_name"] for g in call("res.groups", "read", me[0]["all_group_ids"], fields=["display_name"]))
    if "Timesheets / Administrator" in held:
        record("PASS", "integration user: Timesheets / Administrator")
    else:
        record("FAIL", "integration user: Timesheets / Administrator", "not held")
    for area in ("Project", "Sales"):
        mine = [g for g in held if g.startswith(f"{area} /")]
        (record("PASS", f"integration user: {area} access", ", ".join(mine)) if mine
         else record("FAIL", f"integration user: {area} access", "none held; sale.order.line reads need it"))
    if "Sales / User: Own Documents Only" in held and "Sales / User: All Documents" not in held:
        record("FAIL", "integration user: Sales scope",
               "'Own Documents Only' scopes to orders this user sells; a service account must see every client's")

    # -- mail.mail (decision 0009) ----------------------------------------
    for op, want in (("read", True), ("create", True), ("write", False), ("unlink", False)):
        try:
            allowed = bool(call("mail.mail", "check_access_rights", op, raise_exception=False))
        except xmlrpc.client.Fault as exc:
            record("WARN", f"mail.mail {op}", f"could not determine: {exc.faultString.splitlines()[-1]}")
            continue
        if allowed == want:
            record("PASS", f"mail.mail {op} {'allowed' if allowed else 'denied'}")
        elif want:
            record("FAIL", f"mail.mail {op} allowed", "the daily digest cannot be queued (decision 0009)")
        else:
            record("WARN", f"mail.mail {op} denied", "integration user has more mail.mail access than the minimum")

    # -- every profile field exists, with the expected shape ----------------
    cache: dict[str, dict] = {}
    for pkey, (model, want_type, want_rel) in PROFILE_FIELDS.items():
        fname = profile.get(pkey)
        if not fname:
            record("FAIL", f"profile.{pkey}", "missing from the profile")
            continue
        if model not in cache:
            cache[model] = call(model, "fields_get", [], attributes=["type", "relation", "selection", "store"])
        meta = cache[model].get(fname)
        if meta is None:
            record("FAIL", f"{model}.{fname} (profile.{pkey})", "field does not exist on this instance")
            continue
        problems = []
        if want_type and meta["type"] != want_type:
            problems.append(f"type {meta['type']!r}, expected {want_type!r}")
        if want_rel and meta.get("relation") != want_rel:
            problems.append(f"relation {meta.get('relation')!r}, expected {want_rel!r}")
        if pkey in MUST_BE_STORED and not meta.get("store", True):
            problems.append("not stored (cannot be searched)")
        (record("FAIL", f"{model}.{fname} (profile.{pkey})", "; ".join(problems)) if problems
         else record("PASS", f"{model}.{fname}", f"{meta['type']}"))

    # -- task billability selection carries all three profile values --------
    tb = cache.get("project.task", {}).get(profile.get("task_billable_field", ""), {})
    if tb.get("selection"):
        offered = {v for pair in tb["selection"] for v in pair}
        for pkey in ("task_billable_same_as_project_value", "task_billable_yes_value", "task_billable_no_value"):
            (record("PASS", f"task billable option {profile[pkey]!r}") if profile[pkey] in offered
             else record("FAIL", f"task billable option {profile[pkey]!r}", f"not among {sorted(offered)}"))

    # -- the one thing the API cannot show: the index -----------------------
    record("WARN", f"{profile.get('app_entry_id_field')} is indexed",
           "cannot be verified over the API (CLAUDE.md); confirm by hand in Technical settings")

    # -- employees: sign-in resolves by work_email --------------------------
    emps = call("hr.employee", "search_read", [("active", "=", True)], fields=["name", "work_email", "tz"])
    record("PASS" if emps else "FAIL", "active employees", str(len(emps)))
    no_email = [e["name"] for e in emps if not e["work_email"]]
    if no_email:
        record("WARN", "employees without work_email (cannot sign in)", ", ".join(no_email[:10]))
    dupes = [m for m, n in Counter((e["work_email"] or "").lower() for e in emps if e["work_email"]).items() if n > 1]
    if dupes:
        record("FAIL", "duplicate work_email (sign-in refuses ambiguity)", ", ".join(dupes))
    if domain:
        off = [e["work_email"] for e in emps if e["work_email"] and not e["work_email"].lower().endswith("@" + domain.lower())]
        if off:
            record("WARN", f"work_email outside @{domain} (cannot sign in)", ", ".join(off[:10]))
    no_tz = [e["name"] for e in emps if not e["tz"]]
    if no_tz:
        record("WARN", "employees without a timezone (the app falls back to UTC)", ", ".join(no_tz[:10]))

    # -- test debris must not be here ---------------------------------------
    leftovers = call("account.analytic.line", "search_count", [("name", "like", "e2e-suite")])
    (record("FAIL", "no e2e-suite lines in this instance", f"{leftovers} found: the e2e suite ran against production?")
     if leftovers else record("PASS", "no e2e-suite lines in this instance"))

    fails = sum(1 for lvl, *_ in results if lvl == "FAIL")
    warns = sum(1 for lvl, *_ in results if lvl == "WARN")
    print(f"\n{len(results) - fails - warns} passed, {warns} warnings, {fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
