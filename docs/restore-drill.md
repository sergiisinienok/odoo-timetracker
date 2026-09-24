# Restore drill — step 2.7

Performed 2026-09-24 against the local compose stack (Postgres 18, `backup` sidecar).

## Procedure (also the real restore recipe)

1. Find the dump to restore. Dumps live on the `postgres-backups` volume,
   named `tti-<UTC timestamp>.dump` (custom format), 14 days retained:
   `docker compose exec backup ls -l /backups`
2. **Restore into a scratch database first**, never straight over `tti`:
   ```
   docker compose exec -T db psql -U tti -d postgres -c "create database tti_restore_drill"
   docker compose exec -T backup sh -c \
     'PGPASSWORD=$POSTGRES_PASSWORD pg_restore -h db -U tti -d tti_restore_drill --no-owner /backups/<dump file>'
   ```
3. Check the queue is intact: compare `select count(*) from outbox` and the
   `alembic_version` row against what you expect, and eyeball
   `select state, count(*) from outbox group by state` in the scratch DB.
4. Drop the scratch DB. To restore for real: `docker compose stop api worker`,
   drop and recreate `tti`, `pg_restore` into it as above, `docker compose start api worker`.
   Pending rows resume draining; the worker's reconcile-before-create means a
   row that had already reached Odoo before the crash is not duplicated.

## The drill

Three outbox rows were seeded (one pending create, one failed create, one
pending delete), a dump taken with `docker compose exec backup /bin/sh /backup.sh --once`,
and the dump restored into `tti_restore_drill` as above. A checksum over every
outbox column was computed on both sides.

| | source `tti` | restored `tti_restore_drill` |
|---|---|---|
| outbox rows | 3 | 3 |
| checksum | `6c5d8309ad2ab812a0f48b311755cffa` | `6c5d8309ad2ab812a0f48b311755cffa` |
| alembic version | `44fb3986cc7b` | `44fb3986cc7b` |

`pg_restore` exit status 0. Scratch database dropped and the seeded rows deleted afterwards.

## Not covered

- The drill restored from a dump taken seconds earlier, not from a nightly one
  that had aged on the volume. The nightly schedule (02:00 UTC) and 14-day
  pruning are implemented in `ops/backup.sh` but have not yet run unattended.
- The backup volume lives on the same host as the database volume. It protects
  against a lost queue, not a lost machine; copying it off-host is a Phase 3/4 call.
