# 0004 — `readonly_timesheet` is not user-relative on this instance (contrary to the plan's expectation)

**Discovered:** step 0.2, comparing `readonly_timesheet` on the same
validated line (id 3) between the integration user (Timesheets
Administrator) and Polina (Timesheets User: own timesheets only).

## Assumed

The plan flagged this as a real risk: "our integration account holds
approver rights, so the flag may well read False on a line that is
validated — approvers are allowed to edit. It is therefore not safe as the
app's lock signal on its own."

## Probe showed

Both accounts read `readonly_timesheet=True` on line 3 (validated) and
`False` on line 4 (not validated) — identical readings for both a
high-privilege and a low-privilege user. On this instance, the field
tracks `validated` directly rather than the calling user's own edit
rights.

## Changed

`odoo_profile.json`'s `readonly_is_user_relative` recorded as `false`.

## Consequence

None for the app's design. The plan already committed to date-based
locking via `last_validated_timesheet_date` / `resolve_period_state()`
rather than reading `readonly_timesheet` per line, specifically because
this field's reliability was in question. That choice turns out not to
have been strictly necessary on this instance, but nothing about it needs
to change — it's still correct, still cheaper (no per-line round trip),
and still robust if the field behaves differently elsewhere.

## Re-verify

Once on the real `particlesg.odoo.com` sandbox — this could plausibly
differ from the trial in either direction.
