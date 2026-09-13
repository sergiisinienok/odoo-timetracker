# 0005 — No usable field for assignment validity dates (Appendix D risk #4, materialized)

**Discovered:** step 0.4, scanning `sale.order.line`, `sale.order`, and
`project.sale.line.employee.map` for anything date-related, then
cross-checked against the full plan text.

## This is not a new problem — it's risk #4, already anticipated

Appendix D of the implementation plan lists this exact scenario as risk #4:
*"Neither the sales order nor its lines carry usable start/end dates on
this instance | Validity cannot be enforced as the brief promises; needs a
Studio pair on the order line or dropping the rule | Step 0.4 probe,
escalate to owner."*

Step 0.7 says the same thing more fully: *"If neither the line nor the
order carries usable dates on this instance, stop and report — the
options are then a Studio date pair on the order line or dropping date
enforcement, and that is the owner's call, not Sonnet's."*

So the plan itself already defines both the trigger condition and the two
legitimate resolutions. This decision doc exists to confirm the trigger
fired and record which resolution the owner picked — not to invent a
third path unilaterally.

## What the probe actually found

- `sale.order.line`'s date-matching fields: all inventory/forecast/
  invoicing-at-date concepts (`scheduled_date`, `qty_delivered_at_date`,
  `forecast_expected_date`, etc.) — nothing meaning "this line is valid
  from X to Y," and several of them (`scheduled_date`,
  `forecast_expected_date`) are tied to Odoo's own delivery/procurement
  logic, so even if writable, repurposing them risks side effects
  unrelated to timesheets.
- `sale.order`'s date-matching fields are order-level, not per-employee —
  `date_order`, `validity_date`, `commitment_date` — and Appendix D risk
  #4 already names `validity_date` specifically as "quotation expiry, not
  a delivery window."
- `project.sale.line.employee.map` — not one of the plan's own candidate
  locations for this (0.7 explicitly considered and rejected Studio
  fields *here*, preferring the sales order) — has no date fields beyond
  `create_date`/`write_date` metadata either, for completeness.

## Correction to earlier guidance in this conversation

An earlier version of this document, and my own recommendation before
reading the full plan text, suggested a Studio field on
`project.sale.line.employee.map` as the fallback. That's not what the
plan specifies. Step 0.7 is explicit: if a Studio field becomes
necessary, it goes **on `sale.order.line`**, consistent with "one line
per allocated person means a line-level date is a per-person date" — the
same reasoning that made line-level the preferred location in the first
place, before we knew it didn't exist yet.

## Also investigated: the Planning app

Checked whether `planning.slot` offers a better-integrated alternative
than a Studio field. It's real and does link to our structure
(`employee_id` -> `hr.employee`, `sale_line_id` -> `sale.order.line`,
plus genuine `start_datetime`/`end_datetime` fields) — but it is not one
of the plan's own anticipated resolutions, requires maintaining a second
record per assignment kept in sync with
`project.sale.line.employee.map`, has unverified side effects (calendar
publishing, notifications), and runs against the plan's own stated
minimalism ("there is one less custom field to maintain" — 0.7).
Available if genuinely wanted, not recommended.

## Still deciding

Which of the plan's own two options — a Studio date pair on
`sale.order.line`, or dropping date enforcement — per 0.7, explicitly the
owner's call, not Sonnet's (or Claude's).

## Changed

Resolved: **date enforcement is dropped**, per the plan's own second
option at 0.7 ("dropping date enforcement"). `assignment_start_source`
and `assignment_end_source` are recorded in `odoo_profile.json` as
`null` rather than naming a field — an explicit, deliberate absence, not
an unresolved gap. The domain design already treats an assignment with
no dates set as open-ended rather than invalid (per 1.4's own spec: "An
assignment with no dates set is open-ended, not invalid."), so this
requires no special-casing in Phase 1/2 code beyond what was already
planned — the null values simply mean every assignment resolves as
open-ended.

## Consequence, made explicit

The brief's stated promise — "someone who joins a client mid-month can
log from their assignment start date and not before" — does not hold as
written. What remains: the picker itself is still gated by whether a
`project.sale.line.employee.map` row exists at all (coarse-grained
protection), and the daily cap, period locking, ownership checks, and
approver review of the whole month before invoicing all stay fully
intact. This is a narrow, visible regression against one specific brief
promise, not a broader loosening of guardrails.

## Reversibility

Not permanent. If the real `particlesg.odoo.com` sandbox turns out to
carry a usable date field, or a Studio field on `sale.order.line`
becomes worth adding later, `assignment_start_source`/
`assignment_end_source` can be populated then — the domain logic already
supports both states without a redesign.

## Note for the Phase 0 gate review

The gate checklist's line "Assignment validity dates resolved to real
sales-order fields, named in the profile, and proven to read back" was
written assuming the fields-exist branch of risk #4. Read it as
satisfied in the broader sense the plan actually intends — a decision
was reached and recorded, per 0.7's explicit "that is the owner's call"
— not as a literal mismatch to chase down.
