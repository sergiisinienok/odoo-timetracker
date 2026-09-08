# Odoo Time Tracker

A time-logging app for employees, writing straight into Odoo timesheets, invoiced to clients at each person's rate.

- **Why and what:** [`docs/brief.md`](docs/brief.md) — Draft v7, owned by Sergii. Snapshot only; the canonical copy lives with its owner and this file is refreshed when a new draft lands.
- **How and in what order:** [`docs/implementation-plan.md`](docs/implementation-plan.md) — five phases, Phase 0 (Odoo foundation) through Phase 4 (rollout). Executed step by step by Claude Sonnet, with a human at Phase 0 and at each phase gate.
- **Probe results that changed the plan:** [`docs/decisions/`](docs/decisions/) — one short file per discovery, per ground rule 5 in the implementation plan.

## Status

Phase 0 — Odoo foundation. Nothing past this phase is written until `odoo_profile.json` exists and is committed.

## Ground rule, in one line

Never assume an Odoo field name. Every field this app reads or writes is proven first by a probe script against the live sandbox — see the implementation plan's ground rules before touching `api/` or `web/`, neither of which exist yet.

## Getting started

```
cp .env.example .env   # fill in ODOO_URL, ODOO_DB, ODOO_USER, ODOO_KEY — never commit this file
python3 tools/spike_odoo_timesheet_lock.py
```
