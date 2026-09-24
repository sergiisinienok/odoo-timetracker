# Key rotation — step 2.7

**Status: rehearsed 2026-09-24** against the trial's integration-user key. Record at the bottom.

Rotating is routine, not an incident response: do it on a schedule and any time
a key may have been exposed. The app reads secrets only from `.env`, so every
rotation is "change the value, restart the containers that read it".

## Odoo API key (`ODOO_KEY`) — the one that matters most

Odoo lets a user hold several API keys, so rotate without downtime by
overlapping the old and new key.

1. In Odoo, logged in as the integration user: Preferences → Account Security →
   New API Key. Name it with the date. Copy it once; Odoo never shows it again.
2. Put it in `.env` as `ODOO_KEY` (file must stay mode 600). Never paste it
   into a chat, a commit or a ticket.
3. `docker compose up -d api worker` (recreates both with the new value).
4. Verify: `curl -s localhost/api/readyz | jq .checks.odoo` is `true`, and
   `docker compose logs --since 2m worker api | grep -i "authentication failed"`
   is empty. Also run `python3 tools/p2s07-probe_mail_mail.py` from a shell with
   the new `.env` loaded — it authenticates and exercises real access.
   **Also confirm the containers really hold the new key** — `/readyz` passes
   on the old key too while it is still valid, so it proves nothing here:
   ```
   for s in api worker; do docker compose exec -T $s printenv ODOO_KEY | tr -d '\r\n' | md5; done
   grep '^ODOO_KEY=' .env | cut -d= -f2- | tr -d '\r\n' | md5
   ```
   All three hashes must match (strip the newline from both sides, or they
   won't). If not, `docker compose up -d --force-recreate api worker`.
5. Only after step 4 passes: delete the old key in Odoo (same screen).
6. If step 4 fails, the old key still works. Restore the old value in `.env`,
   `docker compose up -d api worker`, and investigate before retrying.

A bare `Fault 3 / Access Denied` from a script that used to work usually means
the key expired or was deleted — see CLAUDE.md's note on trial key expiry.

## Other secrets

| Secret | Effect of rotating | How |
|---|---|---|
| `SESSION_SECRET` | Signs out every employee | Change value, `docker compose up -d api` |
| `GOOGLE_CLIENT_SECRET` | Sign-in fails until updated | Create a new secret in Google Cloud Console, update `.env`, restart `api`, then delete the old one |
| `POSTGRES_PASSWORD` | Needs `ALTER USER tti PASSWORD '...'` inside Postgres as well as `.env`; changing `.env` alone locks the app out | Alter the role first, update `.env`, `docker compose up -d api worker backup` |

## Rehearsal record

Odoo API key, trial instance, integration user (uid 5), 2026-09-24.

1. New key created in Odoo and written to `.env` by the owner (mode stayed 600).
2. `docker compose up -d api worker`, then verified: `/readyz` 200; zero
   "authentication failed" lines in the logs; `tools/p2s07-probe_mail_mail.py`
   authenticated as uid 5; container key hash equal to `.env`'s.
   (First comparison looked like a mismatch — only because the `.env` side of
   the hash included a trailing newline. Step 4 above now says to strip it.)
3. Old key deleted by the owner.
4. Re-verified after the deletion, by an authenticated call from inside each
   container (`authenticate()` plus `hr.employee search_count`, both succeeded
   as uid 5), the probe again, `/readyz` 200, no auth failures in five minutes.

Gaps: `/readyz` cannot detect a dead key (its Odoo check is the unauthenticated
`version` call), which is why step 4 requires an authenticated check. Whether a
bad key should also fail readiness is worth deciding in 2.8. Not rehearsed:
`SESSION_SECRET`, `GOOGLE_CLIENT_SECRET`, `POSTGRES_PASSWORD`.
