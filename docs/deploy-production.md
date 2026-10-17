# Deploying to production

Target: the Hetzner VM `particles-website` (the same one staging uses), served at
`https://timetracker.particlesglobal.com`, pointed at the production Odoo
`https://particlesglobal-1.odoo.com`.

Status: **a plan, not yet executed.** Nothing here has been run against production. Written
2026-10-17 from `docs/deploy-staging.md`, whose shape it copies; read that first for the reasoning
behind the nginx/Caddy split, which is not repeated here.

## Before anything else: three things that stop this

1. **Ground rule 3 ends here, on purpose.** "Never write to production Odoo until Phase 3" —
   this *is* Phase 3. Pointing the app at `particlesglobal-1` is the step that rule was holding
   back. The owner's go-ahead to cross it should be recorded (a line in `docs/decisions/`) before
   step 7, not assumed from the request to plan the deploy.
2. **Step 2b.2 was never done.** Every Odoo fact in `odoo_profile.json` comes from the trial
   (`edu-timetracking.odoo.com`). The plan's own sandbox, `particlesg.odoo.com`, was skipped
   (decision 0013), and **`particlesglobal-1` is a different instance again.** The probe suite
   must be re-run against the target before the pilot (step 3), including the Studio field
   `x_studio_billable` and the `is_so_line_edited` hand test. Until then the profile is a guess
   about production.
3. **The Phase 2b gate has not passed** (`CLAUDE.md`: needs a real sandbox and the owner's by-hand
   timing of a normal day). Deploying a pilot to production ahead of it is a deliberate
   exception, not a default.

## What differs from staging

| | Staging | Production |
|---|---|---|
| Hostname | `staging.timetracker.particlesglobal.com` | `timetracker.particlesglobal.com` |
| Odoo | trial `edu-timetracking.odoo.com` | `https://particlesglobal-1.odoo.com` |
| Loopback port | `127.0.0.1:8080` | `127.0.0.1:8081` |
| Compose project | directory name (`odoo-timetracker`) | `tti-prod` (set in `.env`) |
| Override file | `docker-compose.staging.yml` | `docker-compose.production.yml` |
| Checkout | `~/odoo-timetracker` | `~/timetracker-prod` |
| nginx block | `docs/deploy/nginx-staging.conf` | `docs/deploy/nginx-production.conf` |
| Odoo key, secrets, Postgres | their own | **their own, never shared with staging** |

Both stacks run side by side. The project name keeps their containers and volumes (database,
backups, logs) separate; a mistake there is the one that could put production data in staging's
database, so check it in step 8.

```
browser ──HTTPS──▶ nginx (existing, 443) ──▶ 127.0.0.1:8081 ─▶ Caddy ─▶ api / static web   (Docker, project tti-prod)
                                                                         worker, Postgres, backup
```

## The configuration scripts

Two, deliberately small:

- **`ops/configure-prod-env.sh`** — run on the VM. Writes `.env` mode 600: generates
  `SESSION_SECRET` and `POSTGRES_PASSWORD`, prompts (hidden) for the Odoo key and Google client
  secret, pins `ODOO_URL`, `PUBLIC_BASE_URL`, `COMPOSE_PROJECT_NAME` and `COMPOSE_FILE`. Refuses to
  overwrite an existing `.env`. Tested in a scratch directory: mode 600, secrets not echoed, second
  run refused.
- **`tools/prod_preflight.py`** — read-only (authenticate, `fields_get`, `read`, `search_read`,
  `check_access_rights`; no create/write/unlink). Checks that the instance matches
  `odoo_profile.json` and that the integration user is provisioned. Exits non-zero on any FAIL.
  Run against the trial it gives `26 passed, 2 warnings, 0 failed` (the warnings are real: two trial
  employees have no `work_email`).

What it deliberately does **not** do is create anything in Odoo. The integration user, the groups,
the Studio fields and the per-employee data are made by a human in the Odoo UI: Studio fields can't
be created over the API from this account (the `ir.model` restriction in decision 0001), and a
script that writes to production is exactly what ground rule 3 exists to prevent. The script's job
is to prove the human did it right.

## 1. Odoo side (human, in `particlesglobal-1`)

Nothing in the app is deployed yet; this is all Odoo configuration. The full walk-through is
`docs/odoo-production-setup.md`; in outline, in this order:

1. **Integration user**: a dedicated Internal User (not a person's account), with
   - Timesheets → **Administrator**;
   - a Project group (User or Administrator);
   - Sales → **User: All Documents**. **Not** "Own Documents Only": it scopes to orders this user
     sells and silently hides every other client's;
   - the group that gives `mail.mail` **read + create** (decision 0009). Decision 0009 records that
     the grant was made on the trial but not which group; look it up on the trial's integration user
     (uid 5) and repeat it. Write the name into 0009 afterwards so the next time isn't a search.
   Its `email` must be set (the digest's sender).
2. **A new API key** for that user, named `production <date>`. Copy it once; it goes straight into
   step 6's prompt.
3. **Studio fields**, with the technical names the profile expects (check, don't trust):
   `hr.employee.x_studio_default_project` (many2one → `project.project`),
   `account.analytic.line.x_studio_timetracking_app_entry_id` (char, **Indexed** — set it in
   Technical settings; the API can't confirm the index, so look at it with your eyes),
   `project.task.x_studio_billable` (selection: *Same as project* / *Billable* / *Not billable*,
   default *Same as project*).
   If Studio generates different names here, **stop**: that's a profile change (ground rule 5),
   not something to edit around.
4. **Employees** the pilot will use: active, with `work_email` equal to their Google address
   (sign-in resolves by exactly that, and refuses zero or two matches) and a timezone.
5. **Per pilot employee**: a default project, and their assignments on the sales order
   (per-employee order lines mapped on the project), as in Phase 0.

## 2. Preflight against production, from your laptop

```
# In a fresh shell, so your trial .env values are not in the environment:
export ODOO_URL=https://particlesglobal-1.odoo.com ODOO_DB=… ODOO_USER=… ODOO_KEY=…
export GOOGLE_HOSTED_DOMAIN=particlesglobal.com
python3 tools/prod_preflight.py
```

Done when it exits 0 with no FAIL. Expect these WARNs and read each one: the unverifiable index,
employees with no `work_email` or timezone. A version mismatch FAIL means the profile's
`odoo_version` is the trial's (`19.0+e`); production's value goes into the regenerated profile in
step 3, not into a loosened check.

## 3. Re-run the probes; regenerate and commit the profile

The Docker image copies `odoo_profile.json` in at build time (`api/Dockerfile`), so the profile
that ships is the one committed. Therefore:

1. Run the Phase 0 probe suite and the Phase 2b probes (`probe_tasks.py`, the `is_so_line_edited`
   hand test from decision 0013) against `particlesglobal-1`. These probes **create** throwaway
   timesheet lines, projects and employees — by design, in a *test project*. Production work is
   limited to a clearly-named test project and test employee, and the owner approves that before
   it runs; nothing touches a real client's order.
2. Regenerate the profile. **`tools/build_profile.py` is named by the plan (2b.2) but does not exist
   in this repo**, so there is no script to run; either write it (a step of its own, with a
   Validate) or assemble the profile by hand from the probes' output. `git diff odoo_profile.json`
   against the trial's; explain every difference in a decision record.
3. Commit the profile. Production is built from that commit.
4. Re-check each trial quirk in `CLAUDE.md` (`has_group()`, the `partner_id` reset,
   `readonly_timesheet`, `create()` returning a list over XML-RPC) and record which still hold.

## 4. DNS, Google, firewall

- DNS: `A` record `timetracker.particlesglobal.com` → the VM's public IP (and `AAAA` if the VM
  answers IPv6 for its other sites). Check it resolves before step 9, or certbot fails.
- Google Cloud Console, on the OAuth client: add the redirect URI exactly,
  `https://timetracker.particlesglobal.com/api/auth/google/callback`. Use a **separate OAuth client
  for production** if you can, so staging's secret can be rotated without signing production out;
  if you share one, remember rotating it affects both.
- Hetzner firewall: nothing new — 80/443 are already open and the stack adds no public port. Do
  **not** publish 8081 or 5432.

## 5. Is there room on the VM?

This is the one thing the staging doc could treat as an aside and this one can't. The VM has 7.6 GB
RAM, **no swap**, and already runs the public website, its admin, **and the staging stack**; now a
second stack (api, worker, Postgres, backup, Caddy) joins them, and the web build (Node) is a memory
spike. Before building:

```
free -h ; docker stats --no-stream      # what staging and the website use now
```

If production plus headroom doesn't fit comfortably, add a swap file or move production to its own
small Hetzner instance. A production app that OOM-kills the public website is worse than a delayed
pilot. Build with `nice -n 19` regardless, and snapshot the VM first (**Hetzner snapshot** is the
rollback point for the whole box).

## 6. Get the code and write `.env`

As the deploy user:

```
git clone https://github.com/sergiisinienok/odoo-timetracker.git timetracker-prod
cd timetracker-prod
git checkout <the commit that includes the regenerated profile>    # a commit hash, not main
./ops/configure-prod-env.sh
set -a && source .env && set +a && python3 tools/prod_preflight.py    # again, from the VM
```

Running the preflight from the VM proves the VM can reach Odoo with the key that's actually in
`.env`, which is the thing that will matter at 07:00 UTC.

The file ends up as:

| Variable | Production value |
|---|---|
| `COMPOSE_PROJECT_NAME` | `tti-prod` |
| `COMPOSE_FILE` | `docker-compose.yml:docker-compose.production.yml` |
| `ODOO_URL` | `https://particlesglobal-1.odoo.com` |
| `ODOO_DB`, `ODOO_USER`, `ODOO_KEY` | prompted — the production integration user's, its own new key |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_HOSTED_DOMAIN` | prompted / `particlesglobal.com` |
| `PUBLIC_BASE_URL` | `https://timetracker.particlesglobal.com` (no trailing slash; the Origin check compares it exactly) |
| `SESSION_SECRET`, `POSTGRES_PASSWORD` | generated, different from staging's |
| `DAILY_HOUR_CAP`, `OPS_DIGEST_TO`, `DIGEST_HOUR_UTC` | prompted / `7` |

## 7. Start and migrate

Migrations are not automatic. Run them before the app takes traffic:

```
docker compose up -d db
docker compose run --rm api alembic upgrade head          # ends: 211bfd794469 (head)
nice -n 19 docker compose up -d --build                   # second terminal: watch free -h
curl -s http://127.0.0.1:8081/api/healthz     # odoo reachable, version_matches_profile true
curl -s -w ' %{http_code}\n' http://127.0.0.1:8081/api/readyz     # 200, every check true
```

Both stacks now exist on the VM. If you run `docker compose` from the wrong checkout you are
operating on the wrong stack; the shell prompt in `~/timetracker-prod` should make that obvious.

## 8. Prove it is not staging

Before nginx exposes anything:

```
docker compose ps                        # names start with tti-prod-
docker volume ls | grep tti-prod         # production has its own postgres-data, postgres-backups, app-logs
docker compose exec api printenv ODOO_URL PUBLIC_BASE_URL     # production values
```

And that the two stacks are really separate: `ss -ltn | grep -E ':(8080|8081)\b'` shows both bound to
`127.0.0.1` only.

## 9. nginx and the certificate

```
sudo cp docs/deploy/nginx-production.conf /etc/nginx/sites-available/timetracker-production
sudo ln -s /etc/nginx/sites-available/timetracker-production /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx              # reload, never restart: the website is live
sudo certbot --nginx -d timetracker.particlesglobal.com
sudo nginx -t && sudo systemctl reload nginx
sudo certbot renew --dry-run
```

The `X-Forwarded-For` overwrite in that file is load-bearing (rate limiting); don't change it to
`$proxy_add_x_forwarded_for`.

## 10. Verify from outside

```
curl -s https://timetracker.particlesglobal.com/api/healthz
curl -s -w ' %{http_code}\n' https://timetracker.particlesglobal.com/api/readyz
curl -sI https://timetracker.particlesglobal.com/        # CSP, X-Frame-Options, HSTS — each once
```

- From your laptop, `nc -vz <vm-public-ip> 8081` and `... 5432` must be refused.
- The website, its admin and **staging** still answer.
- **First real use, with one pilot employee, on a day that isn't going to be invoiced:** sign in
  with a `@particlesglobal.com` account, log 0.25 h on a real assignment, find the line in Odoo,
  edit it, delete it. The Delete button exists (2026-10-17); this is the only way to undo a
  mistaken test line, so confirm it works on production *before* the pilot relies on it.
- Digest: `docker compose exec worker python -m tti.ops` queues one email in Odoo; confirm it
  arrives at `OPS_DIGEST_TO`.

## Things that are different about production

- **Nobody is a test user any more.** The staging doc says "log an hour"; here that is a real
  timesheet line on a real client's order. Use the Delete button and say so to the owner.
- **There is no pilot allowlist.** Sign-in lets in *any* active employee whose `work_email` is in
  the Google domain. A "3–5 person pilot" is therefore three to five people *told* to use it, not
  three to five people *able* to. If that is not acceptable, it needs a small code change (an
  `ALLOWED_EMAILS` setting checked at sign-in) as a step of its own, before step 10. Decide before
  go-live; flagging, not building, here.
- **The pilot runs beside spreadsheets**, so invoices are unaffected (Phase 3). But the lines are
  real Odoo timesheets: validation, the lock date (`last_validated_timesheet_date`) and anything the
  approver does in Odoo apply to them.
- **Backups protect the queue, not the machine.** The nightly dump sits on the same VM. For
  production, copy `postgres-backups` off the host (Hetzner Storage Box, or `rclone` to object
  storage) on a schedule and drill a restore from the *copy* (`docs/restore-drill.md`). The pilot's
  system of record is Odoo, so the Postgres loss case is "lose the queue", but an off-host copy is
  cheap. The backup sidecar has not yet been observed running unattended (Phase 2 gate caveat);
  confirm a dump appears the morning after go-live.
- **Alerting does not exist.** `/readyz` cannot see a dead Odoo key (CLAUDE.md). Add an external
  check on `https://timetracker.particlesglobal.com/api/readyz` (any uptime monitor) and watch for the
  07:00 UTC digest: a missing digest is the signal that the worker or the key is dead.
- **Secrets:** production's `ODOO_KEY` is the highest-value secret here. Rotate it per
  `docs/key-rotation.md` on a schedule and the day anyone with VM access leaves.
- **HSTS** is sent for this hostname only (no `includeSubDomains`); browsers will insist on HTTPS
  for it for a year, which is right for production.

## Updating and rolling back

```
cd ~/timetracker-prod
git fetch && git checkout <new commit>
nice -n 19 docker compose up -d --build
docker compose run --rm api alembic upgrade head      # only if a migration was added
```

Roll back the code with `git checkout <previous commit>` and the same `up -d --build`. Migrations
only go forward; a rollback across a schema change needs a decision first. **Updates are manual and
pinned to a commit** (not `git pull` on `main`): production runs what you chose, and staging runs
what's ahead of it. Undo the deploy: `docker compose down` (no `-v`), remove the nginx symlink,
reload.

## If something goes wrong

Everything in `docs/deploy-staging.md`'s table applies, with port 8081 for 8080. Production-specific:

| Symptom | Likely cause |
|---|---|
| Staging breaks after production starts | both stacks share a project name — check `COMPOSE_PROJECT_NAME` in each `.env`; stop production first |
| `docker compose` in one checkout acts on the other stack | run it from the right directory; check `docker compose ps` names |
| Bind error on `127.0.0.1:8081` | something else holds it; `ss -ltnp \| grep 8081` |
| Preflight FAILs `Sales scope` | the integration user got "Own Documents Only" |
| Sign-in works but a person is "not an employee" | `work_email` differs from their Google address, or two employees share it |
| `healthz` `version_matches_profile: false` | the profile is the trial's; step 3 not done |
| Every write 403 `bad_origin` | `PUBLIC_BASE_URL` differs from the URL in the browser |

## What is verified, and what is not

Verified locally, 2026-10-17:

- `docker-compose.production.yml` renders with the only published port `127.0.0.1:8081` and no
  database port.
- `ops/configure-prod-env.sh` in a scratch directory: output file mode 600, correct fixed values,
  secrets not echoed, refuses to overwrite.
- `tools/prod_preflight.py` against the trial: 26 passed, 2 warnings, 0 failed, exit 0. **Not**
  exercised against production, so it has never seen a real FAIL path for the group, mail.mail or
  duplicate-email checks.

Not verified, needs the real systems: everything in this document that touches production Odoo,
the VM, DNS, certbot, Google, and whether two stacks fit in memory (step 5). Expect small
corrections on the first pass and fix this file when they happen.
