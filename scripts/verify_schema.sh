#!/usr/bin/env bash
# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
# Verify the sol schema is fully migrated.
# Lists all sol.* tables + their indexes. Exits 0 only if all 5 expected tables exist.

set -euo pipefail

EXPECTED=(capabilities dispatches approvals policies learned_tiers)

sudo -u postgres psql -d surge_brain -c "\dt sol.*"
sudo -u postgres psql -d surge_brain -c "\di sol.*"

missing=0
for t in "${EXPECTED[@]}"; do
  sql="SELECT 1 FROM information_schema.tables WHERE table_schema='sol' AND table_name='${t}'"
  exists=$(sudo -u postgres psql -d surge_brain -tAc "${sql}" | tr -d '[:space:]')
  if [[ "$exists" != "1" ]]; then
    echo "MISSING sol.${t}" >&2
    missing=$((missing + 1))
  fi
done

if [[ $missing -gt 0 ]]; then
  exit 1
fi

echo "ok: all ${#EXPECTED[@]} sol.* tables present"
