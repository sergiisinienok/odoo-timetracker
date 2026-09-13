# 0003 — No company-level timesheet validated-through field on this instance

**Discovered:** step 0.2, confirmed across two separate `fields_get` runs
against `res.company` (matching `valid|readonly|lock|approv|closed|frozen`).

## Assumed

The plan's step 0.2 expected a field like `company_validated_through` on
`res.company`, to be used as Phase 2.1's `resolve_period_state()` fallback
when an employee's own `last_validated_timesheet_date` is unset — "falling
back to the company's."

## Probe showed

The full regex-matched field list on `res.company` contains only
accounting-side lock dates — `fiscalyear_lock_date`, `hard_lock_date`,
`tax_lock_date`, `sale_lock_date`, `purchase_lock_date`, `po_lock`, plus
their read-only `user_*` mirrors — and PO double-validation settings.
Nothing timesheet-specific. Identical result on two separate runs.

## Changed

`odoo_profile.json`'s `company_validated_through` recorded as `null` —
genuinely absent on this instance, not merely unconfirmed.

## Forward

Phase 2.1's `resolve_period_state(date, employee_validated_through,
company_validated_through)` needs its company-level fallback reconsidered.
With no such field, an employee who has never been validated by an
approver has no locking signal at all under the current design — meaning
every date for them reads as OPEN, rather than falling back to a
stricter company-wide date. Worth deciding explicitly whether that's the
right default (plausibly yes: an employee nobody has validated yet should
stay editable) or whether a different signal is needed. Not blocking for
Phase 0 — flag for the Phase 0 gate review and for whoever implements
Phase 2.1.

## Re-verify

Once on the real `particlesg.odoo.com` sandbox. Unlikely this differs —
it would be core Enterprise Timesheets behavior, not trial-specific — but
per ground rule 5, don't assume either way.
