# Deploying to staging

Target: an existing Hetzner VM, served at `https://staging.timetracker.particlesglobal.com`,
pointed at the Odoo trial `https://edu-timetracking.odoo.com`.

**Status of this document:** written before the first real deploy. The repo-side
facts (image architectures, migration commands, the database port binding) were
verified locally. The VM-side steps (Docker install, Hetzner firewall, Google
console, DNS) are from general knowledge and have not been run yet — expect small
corrections on the first pass, and fix this file when they happen.

## What is verified, and what is not

Verified in the repo (2026-09-25):

- All four base images (`caddy`, `python`, `node`, `postgres`) are pinned to
  multi-architecture indexes and pull for both `linux/amd64` and `linux/arm64`.
  Earlier, `caddy` and `python` were pinned to arm64-only images, which would have
  failed to build on an x86 VM ("no matching manifest for linux/amd64").
- Postgres is published on `127.0.0.1:5432` only. It used to be `5432:5432` on all
  interfaces, which on a public VM would expose the database (Docker's own
  firewall rules bypass `ufw`).
- `docker compose run --rm api alembic upgrade head` works and ends at
  `211bfd794469 (head)`.

Not yet done: an actual build and run on the VM, and an amd64 build (only the amd64
image pulls were checked, from an arm64 Mac).

## 0. Check the VM

```
uname -m                                         # x86_64 or aarch64 — both work now
sudo ss -tlnp | grep -E ':(80|443)\b'            # must print nothing
```

If something already listens on 80 or 443 (another site on this VM), stop here:
this setup binds those ports itself for Caddy and automatic HTTPS. The alternative
is to run Caddy behind the existing proxy, which is a different configuration.

## 1. DNS and firewall

- DNS: an `A` record, `staging.timetracker.particlesglobal.com` → the VM's public IP.
  Caddy requests its certificate on first start, which needs the name to resolve and
  ports 80 and 443 to be reachable.
- Hetzner Cloud Firewall: inbound 80 and 443 from anywhere; 22 from your own address only.
  Do not rely on `ufw` for Docker-published ports.

## 2. Install Docker

```
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER      # log out and back in afterwards
docker compose version             # v2.24 or newer
```

## 3. Google sign-in

In Google Cloud Console, on the OAuth client the app uses, add this Authorized
redirect URI, exactly:

```
https://staging.timetracker.particlesglobal.com/api/auth/google/callback
```

Local dev uses `http://localhost/api/auth/google/callback`; the same client can hold both.

## 4. Get the code

```
git clone https://github.com/sergiisinienok/odoo-timetracker.git
cd odoo-timetracker
```

If the repository is private, use a read-only deploy key.

## 5. Configure `.env`

```
cp .env.example .env && chmod 600 .env
```

| Variable | Staging value |
|---|---|
| `ODOO_URL` | `https://edu-timetracking.odoo.com` |
| `ODOO_DB`, `ODOO_USER`, `INTERNAL_PROJECT_ID`, `DAILY_HOUR_CAP` | same as the local `.env` |
| `ODOO_KEY` | a **new** key for staging (Odoo → Preferences → Account Security), so it can be rotated or revoked without touching anyone's laptop |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | same as local, after step 3 |
| `GOOGLE_HOSTED_DOMAIN` | `particlesglobal.com` |
| `PUBLIC_BASE_URL` | `https://staging.timetracker.particlesglobal.com` — no trailing slash. The Origin check compares this exactly; any mismatch makes every write return 403 `bad_origin` |
| `CADDY_ADDRESS` | `staging.timetracker.particlesglobal.com` — this is what turns on automatic HTTPS |
| `SESSION_SECRET` | new: `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | new: `openssl rand -hex 24` |
| `OPS_DIGEST_TO` | the ops address |
| `DIGEST_HOUR_UTC` | `7` |

`DATABASE_URL` can stay as in the example; `docker-compose.yml` sets it for the
containers. Never commit `.env` or paste its values into chat or tickets. The
integration user must already have the `mail.mail` grant (decision 0009); on the
same Odoo instance it does.

## 6. Start and migrate

Migrations are not automatic, so run them before the app takes traffic:

```
docker compose up -d db
docker compose run --rm api alembic upgrade head     # ends: 211bfd794469 (head)
docker compose up -d --build
```

## 7. Verify

```
curl -s https://staging.timetracker.particlesglobal.com/api/healthz
curl -s -w ' %{http_code}\n' https://staging.timetracker.particlesglobal.com/api/readyz
```

- `healthz`: `status: ok`, `odoo: reachable`, `version_matches_profile: true`.
- `readyz`: 200 with every check true.
- Browser: valid certificate, sign in with a `@particlesglobal.com` account, log an
  hour, then confirm the line in Odoo.
- The database is not exposed: from your laptop, `nc -vz <vm-public-ip> 5432` must be refused.
- Headers: `curl -sI https://staging.timetracker.particlesglobal.com/` shows the
  CSP, `X-Frame-Options`, and `Strict-Transport-Security`.
- Digest: `docker compose exec worker python -m tti.ops` queues a digest email in
  Odoo (a real email goes to `OPS_DIGEST_TO`).

## Things to know

- **Shared Odoo data.** Staging and any local stack write to the same trial Odoo.
  A local worker also sends the 07:00 UTC digest to the same address, so ops get two;
  clear `OPS_DIGEST_TO` in the local `.env` if that is unwanted.
- **This is the trial, not the real sandbox.** The `saas_trial` quirks in CLAUDE.md
  still apply. A trial API key can expire on its own: a sudden Access Denied means
  check the key first.
- **HSTS.** Once HTTPS is up, browsers refuse plain HTTP to that hostname for a year.
- **Backups.** The nightly dump lives on the same VM (the `postgres-backups` volume).
  It protects against a lost queue, not a lost machine — add Hetzner snapshots or an
  off-host copy before anything real depends on it. Restore: `docs/restore-drill.md`.
- **Logs.** `docker compose logs -f api worker`; rotating files are on the `app-logs` volume.
  See the README's Operations section.
- **Secrets rotation:** `docs/key-rotation.md`.

## Updating and rolling back

```
git pull
docker compose up -d --build
docker compose run --rm api alembic upgrade head      # only needed if a migration was added
```

Roll back the code with `git checkout <previous commit>` and the same `up -d --build`.
Migrations only go forward here; a rollback across a schema change needs a decision
first, not a blind downgrade.

## If something goes wrong

| Symptom | Likely cause |
|---|---|
| Browser certificate error, or Caddy logs an ACME failure | DNS not yet pointing at the VM, or 80/443 blocked by the firewall |
| Google says `redirect_uri_mismatch` | step 3 not done, or `PUBLIC_BASE_URL` differs from the registered URI |
| Every write returns 403 `bad_origin` | `PUBLIC_BASE_URL` does not exactly match the URL in the browser |
| `docker compose` says `POSTGRES_PASSWORD` is missing | `.env` is missing or not in the directory you ran it from |
| `readyz` 503 with `database: false` | migrations not run yet, or the `db` container is unhealthy |
| `healthz` says `odoo: unreachable` or logs show Access Denied | wrong `ODOO_*` values, or the trial key expired |
| Build fails with `no matching manifest for linux/...` | a base image was re-pinned to a single platform; use the multi-arch index digest (see the comments in `docker-compose.yml` and `api/Dockerfile`) |
