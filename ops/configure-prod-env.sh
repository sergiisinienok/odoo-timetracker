#!/usr/bin/env bash
# Writes .env for the PRODUCTION stack — docs/deploy-production.md, step 6.
#
# Generates the secrets that should be random (SESSION_SECRET, POSTGRES_PASSWORD),
# prompts for the ones only a human has (Odoo key, Google client), pins everything
# that is fixed for production, and writes the file mode 600. Secrets are read
# with `read -s`, so they never reach the screen or shell history, and the script
# never echoes them. It refuses to overwrite an existing .env: rotating a value
# is docs/key-rotation.md, not a re-run of this.
#
# Run it on the VM, in the production checkout:   ./ops/configure-prod-env.sh
set -euo pipefail

cd "$(dirname "$0")/.."
umask 077

ENV_FILE=".env"
PUBLIC_URL="https://timetracker.particlesglobal.com"
ODOO_URL_PROD="https://particlesglobal-1.odoo.com"
PROJECT_NAME="tti-prod"
HOSTED_DOMAIN="particlesglobal.com"

if [ -e "$ENV_FILE" ]; then
  echo "$ENV_FILE already exists; not touching it. Move it aside first if you really mean to start over." >&2
  exit 1
fi

ask() {          # ask VAR "prompt" [default]
  local var="$1" prompt="$2" default="${3:-}" value
  read -r -p "$prompt${default:+ [$default]}: " value
  printf -v "$var" '%s' "${value:-$default}"
  [ -n "${!var}" ] || { echo "$var cannot be empty." >&2; exit 1; }
}
ask_secret() {   # ask_secret VAR "prompt"
  local var="$1" prompt="$2" value
  read -r -s -p "$prompt: " value; echo
  printf -v "$var" '%s' "$value"
  [ -n "${!var}" ] || { echo "$var cannot be empty." >&2; exit 1; }
}

echo "Production Odoo: $ODOO_URL_PROD   App: $PUBLIC_URL"
echo "(The Odoo database name for an odoo.com instance is normally its subdomain; tools/prod_preflight.py proves it.)"
ask ODOO_DB    "Odoo database name" "particlesglobal-1"
ask ODOO_USER  "Integration user login (the production one, not a person)"
ask_secret ODOO_KEY "Odoo API key for that user (new key made for production)"
ask GOOGLE_CLIENT_ID "Google OAuth client id"
ask_secret GOOGLE_CLIENT_SECRET "Google OAuth client secret"
ask OPS_DIGEST_TO "Address for the daily ops digest"
ask DAILY_HOUR_CAP "Daily hour cap" "10"

SESSION_SECRET="$(openssl rand -hex 32)"
POSTGRES_PASSWORD="$(openssl rand -hex 24)"

cat > "$ENV_FILE" <<ENV
# Production — written by ops/configure-prod-env.sh. Mode 600. Never commit or paste this.

# Compose: its own project (separate containers and volumes from staging on this VM)
# and the override that keeps Caddy off ports 80/443 (nginx owns them).
COMPOSE_PROJECT_NAME=$PROJECT_NAME
COMPOSE_FILE=docker-compose.yml:docker-compose.production.yml

# Odoo
ODOO_URL=$ODOO_URL_PROD
ODOO_DB=$ODOO_DB
ODOO_USER=$ODOO_USER
ODOO_KEY=$ODOO_KEY

# Google
GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET
GOOGLE_HOSTED_DOMAIN=$HOSTED_DOMAIN

# App
SESSION_SECRET=$SESSION_SECRET
DAILY_HOUR_CAP=$DAILY_HOUR_CAP
PUBLIC_BASE_URL=$PUBLIC_URL

# Postgres
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
DATABASE_URL=postgresql+psycopg://tti:\${POSTGRES_PASSWORD}@db:5432/tti

# Ops digest
OPS_DIGEST_TO=$OPS_DIGEST_TO
DIGEST_HOUR_UTC=7
ENV
chmod 600 "$ENV_FILE"

echo
echo "Wrote $ENV_FILE (mode $(stat -c %a "$ENV_FILE" 2>/dev/null || stat -f %Lp "$ENV_FILE"))."
echo "Next: set -a && source .env && set +a && python3 tools/prod_preflight.py"
