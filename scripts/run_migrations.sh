#!/usr/bin/env bash
# Apply Alembic migrations against the SOL schema.
#
# Pre-conditions:
#   - /etc/sol/db.env contains SOL_DATABASE_URL (640 root:todds)
#   - /opt/sol/venv contains the SOL Python install
#
# Run as user todds.

set -euo pipefail

if [[ ! -r /etc/sol/db.env ]]; then
  echo "/etc/sol/db.env unreadable" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. /etc/sol/db.env
set +a

cd /opt/sol
# shellcheck disable=SC1091
. venv/bin/activate

alembic upgrade head
alembic current
