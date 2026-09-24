#!/bin/sh
# Nightly pg_dump sidecar — step 2.7. Custom-format dumps to /backups,
# pruned after RETENTION_DAYS. Runs forever; compose restarts it if it dies.
set -eu

RETENTION_DAYS="${RETENTION_DAYS:-14}"
BACKUP_HOUR_UTC="${BACKUP_HOUR_UTC:-2}"
export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"

dump_once() {
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  tmp="/backups/.tti-${ts}.dump.partial"
  if pg_dump -h db -U tti -d tti -Fc -f "$tmp"; then
    mv "$tmp" "/backups/tti-${ts}.dump"   # only a complete dump ever gets the real name
    echo "backup ok: tti-${ts}.dump ($(wc -c < "/backups/tti-${ts}.dump") bytes)"
  else
    rm -f "$tmp"
    echo "backup FAILED at ${ts}" >&2
  fi
  find /backups -name 'tti-*.dump' -mtime "+${RETENTION_DAYS}" -print -delete
}

[ "${1:-}" = "--once" ] && { dump_once; exit 0; }

while true; do
  now="$(date -u +%s)"
  next="$(date -u -d "today ${BACKUP_HOUR_UTC}:00" +%s 2>/dev/null || echo $((now + 86400)))"
  [ "$next" -le "$now" ] && next=$((next + 86400))
  sleep $((next - now))
  dump_once
done
