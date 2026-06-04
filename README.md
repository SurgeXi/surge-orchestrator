# surge-orchestrator (SOL)

The **Surge Orchestration Layer** — single auditable surface for every side-effect across the SurgeXi fleet.

Refines [[option-3-unified-surge-design]] and implements the spec in `memory/project_sol_buildable_spec.md` (locked 2026-06-03).

## Status

**Phase 3.1 — shadow mode only.** SOL writes audit rows for every dispatch it receives from Brain / Broker / Surge Runner but does NOT execute and does NOT block. Legacy side-effect channels remain primary. `SOL_ENFORCE=false`.

## Layout

```
src/sol/
  main.py              FastAPI app factory + uvicorn entrypoint
  settings.py          env-driven config
  db.py                SQLAlchemy session + engine
  models/              ORM
  schemas/             pydantic request/response
  api/                 endpoints (dispatch, capabilities, approvals, audit, policies, health)
  policy/              evaluator + hot cache + YAML loader
  auth/                JWT + service tokens + mTLS
  delivery/            approval delivery channels
  executors/           downstream forwarders
  degraded.py          local WAL queue when Postgres is unavailable
  observability/       metrics + structured logging
  admin/               FastAPI + Jinja2 admin UI

alembic/               migrations (DDL per spec §2)
tests/                 unit / integration / migration / stress / chaos
.github/workflows/     test, lint, docker-build
```

## Run locally (dev)

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e .[dev]
export SOL_DATABASE_URL=postgresql+psycopg2://sol_user:...@127.0.0.1:5432/surge_brain
export SOL_ENFORCE=false
export SOL_SHADOW_ENABLED=true
alembic upgrade head
uvicorn sol.main:app --host 127.0.0.1 --port 9320 --reload
```

## Deploy

See `docs/DEPLOY.md` for the surgecore deploy procedure (systemd unit + nginx + venv layout).

## Port

Production: **9320** (the spec named 9300, but it is occupied by `surgexi-command-center` on surgecore).

## Security

- Service tokens: JWT Ed25519, 90-day expiry, refreshed 14 days before expiration.
- Human admins: JWT, 60-minute TTL.
- Callback tokens (one-tap approve/deny): 15-minute TTL.
- mTLS (Phase 3): service-to-service transport, in scope for Week 1 hardening.
- DB user: `sol_user` has read+write on `sol` schema only — no access to other Brain tables.

## Rollback

Set `SOL_SHADOW_ENABLED=false` in each calling agent's EnvironmentFile and restart that agent. Shadow hooks become no-ops. SOL service can keep running.

## Spec

The full architecture + 7-week migration plan lives in `memory/project_sol_buildable_spec.md`. Do not redefine it here.
