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

## Operations

**Health.** `/api/healthz` is liveness (the process answers). `/api/readyz` is readiness: Odoo reachable, profile loaded, Postgres reachable, oldest pending outbox row under 15 minutes. It returns 503 with the failing check named when not ready.

```
curl -s http://localhost/api/readyz | jq .
```

**Logs.** JSON, one object per line, to stdout and to rotating files (10 MB x 5 per service) on the `app-logs` volume.

```
docker compose logs -f api worker                      # live, both services
docker compose logs --since 1h worker | jq -c 'select(.level=="ERROR")'
docker compose exec api tail -n 100 /var/log/tti/api.log
docker compose exec worker ls -l /var/log/tti/         # rotated files
```

**Daily digest.** The worker queues one `mail.mail` in Odoo at `DIGEST_HOUR_UTC` (default 07:00) to `OPS_DIGEST_TO`; Odoo's outgoing-mail cron delivers it. Send one now with `docker compose exec worker python -m tti.ops`. Needs the integration user's `mail.mail` grant — see `docs/decisions/0009-integration-user-cannot-use-mail-mail.md`.

**Backups.** The `backup` service writes a `pg_dump -Fc` to the `postgres-backups` volume nightly at 02:00 UTC and deletes dumps older than 14 days. Take one now: `docker compose exec backup /bin/sh /backup.sh --once`. Restore procedure and the recorded drill: [`docs/restore-drill.md`](docs/restore-drill.md).

**Secrets.** `.env` must be mode 600. Key rotation: [`docs/key-rotation.md`](docs/key-rotation.md).
