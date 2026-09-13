# 0001 — Odoo 19 / trial instance RPC quirks (has_group, field renames, empty domain)

**Discovered:** step 0.1, while confirming the integration user's Timesheets
rights via `spike_odoo_timesheet_lock.py` against `edu-timetracking.odoo.com`
(a free/eval trial, not yet the real `particlesg.odoo.com` sandbox — see
"Re-verify" below).

## Assumed

`spike_odoo_timesheet_lock.py`, as drafted from the plan, called
`res.users.has_group(group_ext_id)` over XML-RPC to check whether the
integration user held `hr_timesheet.group_hr_timesheet_approver`, per the
method's normal documented behaviour.

## Probe showed

- `has_group()` faulted on every call, including for `base.group_user` (a
  group every authenticated user holds):
  `TypeError: ResUsers.has_group() missing 1 required positional argument:
  'group_ext_id'` — despite the argument being passed correctly. The
  traceback runs through a `saas_trial` controller wrapping the RPC
  dispatcher, which is plausibly the cause: trial databases may restrict or
  mangle non-CRUD method calls on purpose. Not confirmed against a
  non-trial instance.
- `res.users.groups_id` doesn't exist on Odoo 19 — renamed to `group_ids`.
- `res.groups.category_id` doesn't exist on Odoo 19 either — there's a
  `privilege_id` many2one instead, and no plain-text category field.
  `display_name` on `res.groups` still includes the category prefix (e.g.
  `"Timesheets / Administrator"`), which works as a substitute.
- ~~`search_read` with an empty `[]` domain raises a ValueError under
  Odoo 19's rewritten domain parser~~ — **wrong, corrected in
  `0002-domain-argument-convention.md`.** This wasn't real Odoo behavior;
  it was this session's own `call()` helper being invoked with the domain
  double-wrapped in an extra list.
- `ir.model.data` (needed to resolve a group's technical XML id) is itself
  access-restricted to users holding the "Access Rights" administration
  group — an ordinary internal user, even with high app-level permissions,
  can't read it.
- `ir.model` is access-restricted the same way as `ir.model.data` — same
  "Access Rights" administration group requirement. Confirmed in step 0.4.
  General lesson: don't reach for `ir.*` registry models with this
  integration user; `fields_get()`'s own `type`/`relation` attributes
  already answer "does this field exist" and "what does it point to"
  without needing model-level introspection at all.

## Changed

- Group membership is now checked by reading `res.users.all_group_ids`,
  then `res.groups.read(ids, fields=["display_name"])` and matching on the
  label, instead of calling `has_group()`. Patched directly into
  `spike_odoo_timesheet_lock.py`.
- Any future probe listing records with no real filter uses an explicit
  always-true domain, e.g. `[('id', '>', 0)]`, never `[]`.
- Field name to use in new probe code: `group_ids`, not `groups_id`.

## Re-verify

Once probing moves to the real `particlesg.odoo.com` sandbox: re-run
`has_group()` there directly. If it works fine on a non-trial instance,
this was trial-specific, and the `all_group_ids`/`display_name` workaround
can stay scoped to trial testing rather than becoming the app's permanent
pattern in `api/src/tti/odoo/client.py`. If it still fails, this is an
Odoo 19 issue generally and the workaround becomes the real approach.

## Also noted, same session

`res.company`'s field list (via `fields_get`, regex matching
`valid|readonly|lock|approv|closed|frozen`) shows no timesheet-related
lock/validated-through field at all — only accounting-side lock dates
(`fiscalyear_lock_date`, `hard_lock_date`, `tax_lock_date`, etc.). This
suggests `company_validated_through`, the plan's expected company-level
fallback for period locking, may not exist on this instance. Not yet
confirmed as a genuine absence vs. something outside the regex's reach —
worth an explicit, unfiltered field listing before concluding either way,
and worth flagging forward to Phase 2.1's `resolve_period_state()`, which
currently assumes this fallback exists.
