# 0006 — sale.order.line's `_at_date` fields are misleading without their intended read context

**Discovered:** step 0.9, checking whether a flat-rate line's invoiceable
amount moves when hours are logged against it.

## What happened

`probe_flat_rate.py`'s before/after check initially flagged a failure:
`amount_to_invoice_at_date` went from `0.0` to `35000.0` after logging 5
hours against a €7,000 fixed-price line — exactly `price_unit (7000) ×
unit_amount (5)`.

Every properly `monetary`-typed field told a different, consistent story
and stayed completely flat: `amount_to_invoice` (8610.0 → 8610.0),
`untaxed_amount_to_invoice` (7000.0 → 7000.0), `qty_to_invoice` (1.0 →
1.0), `qty_invoiced` (0.0 → 0.0), `invoice_status` ('to invoice' → 'to
invoice'). These are the fields that actually govern what an invoice run
produces.

## Why

`amount_to_invoice_at_date` (like `qty_delivered_at_date` and
`qty_invoiced_at_date`, both seen in 0.4's date scan but not investigated
at the time) is a plain `float`, not `monetary`, with a generic label
("Amount") — consistent with being a forecast/report field meant to be
read with a specific date passed via the RPC call's context, not read
plainly the way every probe in this project reads fields. Read without
that context, it appears to compute something closer to
`price_unit × qty_delivered` — a delivery-based calculation that doesn't
apply to a fixed-price (`ordered_prepaid`) line, and doesn't match what
any of the real invoicing fields showed.

## Changed

`probe_flat_rate.py`'s pass/fail check now excludes any
`_at_date`-suffixed field, checking only the properly-typed invoicing
fields that actually govern invoice generation.

## General lesson

Any `_at_date`-suffixed field on this instance should be treated as
context-dependent and not trusted from a plain read — this is the second
time this pattern has appeared. If Phase 1/2 code ever genuinely needs
one of these fields, pass the context it expects; don't read it the way
every other field in this project has been read.
