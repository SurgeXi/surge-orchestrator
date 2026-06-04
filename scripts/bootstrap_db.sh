#!/usr/bin/env bash
# Bootstrap the SOL database role + schema on the Brain Postgres.
#
# Idempotent. Run as root on surgecore once at provisioning. Generates a
# random password, creates role sol_user with login + schema-owner privileges
# scoped strictly to schema "sol", and writes /etc/sol/db.env with 640 perms.
#
# Pre-conditions:
#   - postgres superuser available via `sudo -u postgres psql`
#   - brain DB name is "surge_brain"
#   - /etc/sol/ exists (mkdir -p /etc/sol /etc/sol/keys /var/lib/sol/wal /var/log/sol)
#
# Re-runs are safe: the role + schema are reused, the password is rotated, and
# /etc/sol/db.env is rewritten.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "must run as root" >&2
  exit 1
fi

DB_NAME="${DB_NAME:-surge_brain}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
ROLE_NAME="${ROLE_NAME:-sol_user}"
DBENV_PATH="${DBENV_PATH:-/etc/sol/db.env}"
DBENV_OWNER="${DBENV_OWNER:-root:todds}"

PASS="$(openssl rand -base64 32 | tr -d '+/=' | head -c 32)"

sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$ROLE_NAME') THEN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '$ROLE_NAME', '__PWD__');
  END IF;
END
\$\$;
CREATE SCHEMA IF NOT EXISTS sol AUTHORIZATION $ROLE_NAME;
GRANT USAGE ON SCHEMA sol TO $ROLE_NAME;
GRANT ALL PRIVILEGES ON SCHEMA sol TO $ROLE_NAME;
ALTER DEFAULT PRIVILEGES IN SCHEMA sol GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO $ROLE_NAME;
ALTER DEFAULT PRIVILEGES IN SCHEMA sol GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO $ROLE_NAME;
SQL

# Rotate the password via a second statement so it does not appear in shell history
# or get expanded incorrectly inside the heredoc DO block.
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 \
  -c "ALTER ROLE $ROLE_NAME WITH LOGIN PASSWORD '$PASS';"

umask 0177
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
printf 'SOL_DATABASE_URL=postgresql+psycopg2://%s:%s@%s:%s/%s\n' \
  "$ROLE_NAME" "$PASS" "$DB_HOST" "$DB_PORT" "$DB_NAME" >"$tmp"
mv "$tmp" "$DBENV_PATH"
chmod 640 "$DBENV_PATH"
chown "$DBENV_OWNER" "$DBENV_PATH"

echo "ok: role=$ROLE_NAME schema=sol dbenv=$DBENV_PATH (640, $DBENV_OWNER)"
