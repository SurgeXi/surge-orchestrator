<!-- Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved. -->
# SOL deploy notes — surgecore

Production node: **surgecore-dell** (Tailscale name `surgecore`). Port **9320** (the spec name was 9300, but that port is held by `surgexi-command-center`; the deviation is recorded in `README.md`).

## One-time provisioning

```bash
# As root on surgecore:
mkdir -p /opt/sol /etc/sol/keys /var/lib/sol/wal /var/log/sol
chown -R todds:todds /opt/sol /var/lib/sol/wal /var/log/sol
chmod 750 /etc/sol /etc/sol/keys
```

## DB user (read+write on sol schema only)

```sql
-- as postgres superuser, against the surge_brain database:
CREATE ROLE sol_user LOGIN PASSWORD '<from /etc/sol/db.env>';
GRANT USAGE ON SCHEMA sol TO sol_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA sol TO sol_user;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA sol TO sol_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA sol GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sol_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA sol GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO sol_user;
-- explicit: no rights outside sol schema. Default privs on public/etc. are untouched.
```

## Environment files (600-perm)

```
/etc/sol/db.env             SOL_DATABASE_URL=postgresql+psycopg2://sol_user:...@127.0.0.1:5432/surge_brain
/etc/sol/service-tokens.env (placeholder; populated as fleet services bootstrap)
/etc/sol/keys/jwt_signing.key   Ed25519 private key (PEM, 600 todds:todds)
/etc/sol/keys/jwt_signing.pub   Ed25519 public  key (PEM, 644 todds:todds)
```

## Deploy

```bash
sudo -u todds bash <<'EOF'
cd /opt
git clone https://github.com/SurgeXi/surge-orchestrator.git sol
cd /opt/sol
python3.12 -m venv venv
. venv/bin/activate
pip install --no-cache-dir --upgrade pip wheel
pip install --no-cache-dir -e .
EOF
```

## Migrations

```bash
sudo -u todds bash -lc '
  set -a; . /etc/sol/db.env; set +a
  cd /opt/sol
  . venv/bin/activate
  alembic upgrade head
'
```

## Seed capabilities

```bash
sudo -u todds bash -lc '
  set -a; . /etc/sol/db.env; set +a
  cd /opt/sol
  . venv/bin/activate
  PYTHONPATH=src python scripts/seed_capabilities.py
'
```

## Systemd unit

`/etc/systemd/system/sol.service` (root-owned, 644):

```ini
[Unit]
Description=Surge Orchestration Layer (SOL)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=todds
Group=todds
WorkingDirectory=/opt/sol
EnvironmentFile=/etc/sol/db.env
EnvironmentFile=-/etc/sol/service-tokens.env
Environment=PYTHONPATH=/opt/sol/src
Environment=SOL_PORT=9320
Environment=SOL_HOST=0.0.0.0
Environment=SOL_ENFORCE=false
Environment=SOL_SHADOW_ENABLED=true
Environment=SOL_ENVIRONMENT=production
Environment=SOL_POLICY_YAML_PATH=/etc/sol/policy.yaml
ExecStart=/opt/sol/venv/bin/uvicorn sol.main:app --host 0.0.0.0 --port 9320 --workers 2
Restart=on-failure
RestartSec=2
StandardOutput=append:/var/log/sol/sol.log
StandardError=append:/var/log/sol/sol.log

# Sandbox
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/log/sol /var/lib/sol/wal
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sol.service
sudo systemctl status sol.service
curl -sS http://127.0.0.1:9320/healthz
curl -sS http://127.0.0.1:9320/readyz
```

## nginx (Tailscale-only ingress)

Place under `/etc/nginx/sites-available/sol.conf`:

```nginx
server {
    listen 100.98.123.125:9320;   # Tailscale interface only
    server_name sol.surgexi.com sol.internal;

    location / {
        proxy_pass http://127.0.0.1:9320;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Phase 3.1 Week 1 ships listener on 127.0.0.1:9320 only; nginx exposure to Tailscale lands once mTLS is wired.

## Rollback

```bash
# Disable shadow hooks in every calling agent's EnvironmentFile:
sudo sed -i 's/^SOL_SHADOW_ENABLED=.*/SOL_SHADOW_ENABLED=false/' /etc/systemd/system/brain.service.d/*.conf || true
sudo systemctl restart brain      # and similarly broker, surge-runner

# SOL service can stay running (idle); no need to stop it.
sudo systemctl status sol
```
