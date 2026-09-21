# 0007 — GOOGLE_HOSTED_DOMAIN is particlesglobal.com, not particles.global

**Discovered:** step 1.3, before writing the `hd`-claim check.

## What happened

`docs/implementation-plan.md`'s own `.env.example` (Appendix, around the
sample env block) assumes:

```
ODOO_USER=integration@particles.global
GOOGLE_HOSTED_DOMAIN=particles.global
```

But every real `hr.employee` record in the live trial has a `work_email`
on a different domain entirely:

```
id=1  Sergii Sinienok             s.sinienok@particlesglobal.com
id=2  Polina Employee Test        polina@particlesglobal.com
id=3  Third Test Employee (Flat Rate)   work_email: False
```

`particlesglobal.com` also matches the marketing site fetched for Appendix
F's brand tokens (`particlesglobal.com` — see "What came from the site").
`particles.global` only appears as the login domain of the *integration*
service account, which is an Odoo-internal login string, not necessarily
a real Google Workspace domain.

## Why

The plan's `.env.example` was written with `particles.global` as a
plausible-looking placeholder before any real employee data existed to
check it against. Once real `hr.employee` rows existed (from Phase 0
probing), they disagreed with that placeholder and nothing had gone back
to reconcile it.

## Changed

Confirmed with the owner directly (not inferred): **`particlesglobal.com`**
is the real company Google Workspace domain. `GOOGLE_HOSTED_DOMAIN` in
`.env` / `.env.example` is set to `particlesglobal.com`. The `hd`-claim
check in `api/src/tti/auth/` compares against this value, read from
config — never hardcoded inline.

`integration@particles.global` (the Odoo login for the API service
account, from step 0.1) is unaffected — it's an Odoo login string, not a
Google account, and isn't subject to the `hd` check at all.

## General lesson

A value copied into `.env.example` before Phase 0 produced real data is a
guess, not a fact, even when it looks plausible. Re-check every such
placeholder against live data (or ask) before the code that enforces it
gets written, same as any other Odoo field or business fact.
