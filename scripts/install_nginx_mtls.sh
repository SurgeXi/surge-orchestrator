#!/usr/bin/env bash
# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
# Install or re-install the SOL mTLS nginx site.
#
# Idempotent:
#   - Generates /etc/sol/nginx-shared-secret (mode 640 root:todds) once.
#   - Renders /etc/nginx/sites-available/sol-mtls from
#     /opt/sol/scripts/nginx-sol-mtls.conf with the secret substituted in.
#   - Symlinks into sites-enabled, runs nginx -t, reloads.
#
# Run as root on surgecore. Existing nginx must be running.
set -euo pipefail

SECRET_FILE=/etc/sol/nginx-shared-secret
TEMPLATE=/opt/sol/scripts/nginx-sol-mtls.conf
RENDERED=/etc/nginx/sites-available/sol-mtls
SITE_LINK=/etc/nginx/sites-enabled/sol-mtls

if [[ ! -f "$TEMPLATE" ]]; then
    echo "ERROR: template not found at $TEMPLATE" >&2
    exit 2
fi

if [[ ! -f "$SECRET_FILE" ]]; then
    echo "Generating fresh nginx shared secret at $SECRET_FILE"
    openssl rand -base64 48 | tr -d '\n' > "$SECRET_FILE"
    chmod 640 "$SECRET_FILE"
    chgrp todds "$SECRET_FILE" 2>/dev/null || true
else
    echo "Reusing existing $SECRET_FILE"
fi

SECRET=$(cat "$SECRET_FILE")

# Render template — replace {{ NGINX_SHARED_SECRET }} with the actual value.
# Using a delimiter unlikely to appear in a base64 secret.
sed "s|{{ NGINX_SHARED_SECRET }}|${SECRET}|g" "$TEMPLATE" > "$RENDERED"
chmod 640 "$RENDERED"

ln -sf "$RENDERED" "$SITE_LINK"

if nginx -t; then
    systemctl reload nginx
    echo "OK: SOL mTLS nginx site installed + reloaded."
else
    echo "ERROR: nginx -t failed; site NOT enabled." >&2
    exit 3
fi
