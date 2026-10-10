# Deploying to staging

Target: the existing Hetzner VM `particles-website`, served at
`https://staging.timetracker.particlesglobal.com`, pointed at the Odoo trial
`https://edu-timetracking.odoo.com`.

## What we know about the VM

From the owner's terminal, 2026-09-25:

- Hetzner, `x86_64`, 4 vCPU, 7.6 GB RAM (about 6 GB free), **no swap**, 50 GB free disk.
- **nginx already owns ports 80 and 443** (sites `default`, `particles`, `strapi`). This VM
  serves the public website, so nothing here may take those ports or restart nginx.
- certbot manages one certificate per hostname (`particlesglobal.com`,
  `admin.particlesglobal.com`); there is no wildcard, so the staging hostname needs its
  own certificate.
- Docker is not installed.

## The shape of the deploy

```
browser ──HTTPS──▶ nginx (existing, port 443, certbot certificate)
                     │  plain HTTP, loopback only
                     ▼
                 127.0.0.1:8080 ─▶ Caddy ─▶ api / static web build      (Docker)
                                            worker, Postgres, backup
```

nginx terminates TLS. The stack's Caddy serves plain HTTP on `127.0.0.1:8080` and is
not reachable from outside the VM. `docker-compose.staging.yml` makes that change and
drops the database port entirely; the base `docker-compose.yml` is unchanged.

If you ever deploy to a VM with **free** ports 80/443, skip the override and nginx
steps: set `CADDY_ADDRESS` to the hostname in `.env` and Caddy gets its own certificate.

## What is verified, and what is not

Verified locally (2026-09-25), by running steps 5–8 as a second, separate copy of the
stack (own project name and volumes, since removed) and putting a real nginx in front
of it with this doc's config:

- All four base images (`caddy`, `python`, `node`, `postgres`) are pinned to
  multi-architecture indexes and pull for both `linux/amd64` and `linux/arm64`. Earlier
  `caddy` and `python` were arm64-only pins and would not have built on this VM.
- With the override, the only published port is `127.0.0.1:8080`; `db`, `api`, `worker`
  publish nothing. (My first draft used `!reset` for that list and published *no* port
  for Caddy; `!override` is correct.)
- Starting from an empty database, `alembic upgrade head` reaches `211bfd794469 (head)`,
  then `/api/healthz` and `/api/readyz` are healthy on `127.0.0.1:8080`.
- Through nginx: each security header appears exactly once; a body over 64 KB gets 413;
  33 anonymous requests each claiming a different `X-Forwarded-For` were throttled after
  30 — a client cannot dodge the rate limit by spoofing.
- Behind a proxy the api used to see the proxy's address for everyone, so all
  unauthenticated users shared one 30-a-minute bucket (shown: client B was refused
  because client A had used it up). The Caddyfile now trusts forwarded headers from
  private addresses only, which fixes that.

**Not yet verified** (needs the real VM): the Docker install, the Hetzner firewall,
Google console changes, DNS, certbot, the amd64 build itself (only the amd64 image pulls
were checked, from an arm64 Mac), and TLS-dependent behaviour such as the `Secure`
session cookie over real HTTPS. Expect small corrections on the first pass and fix this
file when they happen.

## 1. DNS and firewall

- DNS: an `A` record, `staging.timetracker.particlesglobal.com` → the VM's public IP
  (and an `AAAA` if the VM answers on IPv6 for its other sites).
- Hetzner Cloud Firewall: nothing new to open — 80 and 443 are already open for the
  website, and the staging stack adds no public port. Confirm 22 is limited to your
  address. Do **not** publish 8080 or 5432 publicly.

## 2. Install Docker

This box serves the public site, so first take a **Hetzner snapshot** as a rollback point.
Then install Docker's official packages (Ubuntu's `docker.io` and the snap package do not
reliably include the Compose v2 plugin, and the override file needs Compose v2.24+):

```
curl -fsSL https://get.docker.com | sudo sh
docker compose version            # v2.24 or newer
sudo ufw status                   # note: Docker adds its own firewall rules; we publish loopback only
```

Prefer a non-root deploy user in the `docker` group over deploying as root (the `docker`
group is root-equivalent, so only give it to people who should have that):

```
sudo adduser deploy && sudo usermod -aG docker deploy
```

## 3. Google sign-in

In Google Cloud Console, on the OAuth client the app uses, add this Authorized redirect
URI, exactly:

```
https://staging.timetracker.particlesglobal.com/api/auth/google/callback
```

Local dev uses `http://localhost/api/auth/google/callback`; the same client can hold both.

## 4. Get the code

As the deploy user:

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
| `COMPOSE_FILE` | `docker-compose.yml:docker-compose.staging.yml` — so every plain `docker compose` command on the VM includes the override; forgetting it would bind Caddy to 80/443 and fail against nginx |
| `ODOO_URL` | `https://edu-timetracking.odoo.com` |
| `ODOO_DB`, `ODOO_USER`, `DAILY_HOUR_CAP` | same as the local `.env` |
| `ODOO_KEY` | a **new** key for staging (Odoo → Preferences → Account Security), so it can be rotated or revoked without touching anyone's laptop |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | same as local, after step 3 |
| `GOOGLE_HOSTED_DOMAIN` | `particlesglobal.com` |
| `PUBLIC_BASE_URL` | `https://staging.timetracker.particlesglobal.com` — no trailing slash. The Origin check compares it exactly; any mismatch makes every write return 403 `bad_origin` |
| `SESSION_SECRET` | new: `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | new: `openssl rand -hex 24` |
| `OPS_DIGEST_TO` | the ops address |
| `DIGEST_HOUR_UTC` | `7` |

`CADDY_ADDRESS` is not needed: the override sets it to `:80`. `DATABASE_URL` can stay as
in the example; `docker-compose.yml` sets it for the containers. Never commit `.env` or
paste its values into chat or tickets. The integration user must already have the
`mail.mail` grant (decision 0009); on this Odoo instance it does.

## 6. Start and migrate

Migrations are not automatic, so run them before the app takes traffic. There is no swap
and a public site shares the box, so build at low priority and watch memory:

```
docker compose up -d db
docker compose run --rm api alembic upgrade head          # ends: 211bfd794469 (head)
nice -n 19 docker compose up -d --build                   # in another terminal: watch free -h
```

Then, **on the VM**, before touching nginx:

```
curl -s http://127.0.0.1:8080/api/healthz     # status ok, odoo reachable, version_matches_profile true
curl -s -w ' %{http_code}\n' http://127.0.0.1:8080/api/readyz    # 200, every check true
```

## 7. nginx and the certificate

```
sudo cp docs/deploy/nginx-staging.conf /etc/nginx/sites-available/timetracker-staging
sudo ln -s /etc/nginx/sites-available/timetracker-staging /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx              # reload, never restart: the website is live
sudo certbot --nginx -d staging.timetracker.particlesglobal.com
sudo nginx -t && sudo systemctl reload nginx
sudo certbot renew --dry-run                              # the renewal path works for the new certificate
```

The file is HTTP-only on purpose; `certbot --nginx` adds the port-443 block, the
certificate paths and the HTTP→HTTPS redirect. The new `server_name` does not touch the
existing sites. It overwrites `X-Forwarded-For` with the real client address rather than
appending — do not change that to `$proxy_add_x_forwarded_for`, or clients could spoof
the address the api rate-limits on.

## 8. Verify from outside

```
curl -s https://staging.timetracker.particlesglobal.com/api/healthz
curl -s -w ' %{http_code}\n' https://staging.timetracker.particlesglobal.com/api/readyz
curl -sI https://staging.timetracker.particlesglobal.com/     # CSP, X-Frame-Options, HSTS — each once
```

- Browser: valid certificate, sign in with a `@particlesglobal.com` account, log an hour,
  then confirm the line in Odoo. This also confirms the `Secure` session cookie over HTTPS.
- Nothing extra is exposed: from your laptop, `nc -vz <vm-public-ip> 8080` and
  `nc -vz <vm-public-ip> 5432` must both be refused.
- The existing sites still work (open the main website and admin site).
- Digest: `docker compose exec worker python -m tti.ops` queues a digest email in Odoo (a
  real email goes to `OPS_DIGEST_TO`).

## Things to know

- **Shared box.** Staging shares CPU, RAM and disk with the public website, and Docker adds
  firewall rules alongside the existing ones. A separate small instance would isolate them.
  If memory gets tight (`free -h`, no swap), stop the stack before the website suffers:
  `docker compose stop`.
- **Shared Odoo data.** Staging and any local stack write to the same trial Odoo. A local
  worker also sends the 07:00 UTC digest to the same address, so ops get two; clear
  `OPS_DIGEST_TO` in the local `.env` if that is unwanted.
- **This is the trial, not the real sandbox.** The `saas_trial` quirks in CLAUDE.md still
  apply. A trial API key can expire on its own: a sudden Access Denied means check the key.
- **HSTS.** The stack sends HSTS for this hostname only (no `includeSubDomains`), so it
  does not affect the main site. Browsers will insist on HTTPS for the staging hostname for a year.
- **Backups.** The nightly dump lives on the same VM (the `postgres-backups` volume). It
  protects against a lost queue, not a lost machine — the Hetzner snapshot or an off-host
  copy covers that. Restore: `docs/restore-drill.md`.
- **Logs.** `docker compose logs -f api worker`; rotating files are on the `app-logs` volume.
- **Secret rotation:** `docs/key-rotation.md`.

## Updating and rolling back

```
git pull
nice -n 19 docker compose up -d --build
docker compose run --rm api alembic upgrade head      # only needed if a migration was added
```

Roll back the code with `git checkout <previous commit>` and the same `up -d --build`.
Migrations only go forward here; a rollback across a schema change needs a decision first,
not a blind downgrade. Undo the whole deploy with `docker compose down` (keep `-v` off
unless you mean to delete the database) and remove the nginx symlink and reload.

## If something goes wrong

| Symptom | Likely cause |
|---|---|
| nginx returns 502 | the stack is not up on `127.0.0.1:8080` — check step 6's local curl first |
| `docker compose` fails to bind port 80/443 | `COMPOSE_FILE` is missing the staging override (step 5) |
| certbot fails to issue | DNS for the hostname not resolving to this VM yet, or the nginx block is not loaded |
| Google says `redirect_uri_mismatch` | step 3 not done, or `PUBLIC_BASE_URL` differs from the registered URI |
| Every write returns 403 `bad_origin` | `PUBLIC_BASE_URL` does not exactly match the URL in the browser |
| `docker compose` says `POSTGRES_PASSWORD` is missing | `.env` is missing or not in the directory you ran it from |
| `readyz` 503 with `database: false` | migrations not run yet, or the `db` container is unhealthy |
| `healthz` says `odoo: unreachable`, or logs show Access Denied | wrong `ODOO_*` values, or the trial key expired |
| Sign-in page loads but people get throttled (429) | nginx is appending to `X-Forwarded-For`, or `trusted_proxies` was removed from the Caddyfile |
| Build fails with `no matching manifest for linux/...` | a base image was re-pinned to a single platform; use the multi-arch index digest (see the comments in `docker-compose.yml` and `api/Dockerfile`) |
