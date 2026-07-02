<!-- Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved. -->
# surge-orchestrator (SOL)

> A single, auditable control plane for every side-effect an AI agent fleet takes — one place to authorize, log, gate, and dispatch actions.

<!-- Badges: update the CI badge path if the workflow file is renamed. -->
[![ci](https://github.com/SurgeXi/surge-orchestrator/actions/workflows/test.yml/badge.svg)](https://github.com/SurgeXi/surge-orchestrator/actions/workflows/test.yml)
[![lint](https://github.com/SurgeXi/surge-orchestrator/actions/workflows/lint.yml/badge.svg)](https://github.com/SurgeXi/surge-orchestrator/actions/workflows/lint.yml)
[![license](https://img.shields.io/badge/license-source--available-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)

The **Surge Orchestration Layer (SOL)** is a FastAPI service that converges three
things most agent stacks scatter across the codebase — **policy evaluation**,
**audit logging**, and **action dispatch** — behind one narrow interface. When an
autonomous agent wants to do something with a consequence (call a tool, send a
message, write to a system of record), it asks SOL. SOL records the request,
evaluates it against policy, optionally routes it for human approval, and only
then forwards it to the downstream executor. The result: a single query answers
"what did the fleet do, why was it allowed, and who approved it."

## Architecture

```mermaid
flowchart TD
    AG[Agents / callers] -->|dispatch request| API[SOL API<br/>FastAPI]
    API --> AUTH[Auth<br/>JWT + service tokens]
    AUTH --> POL[Policy evaluator<br/>hot-cached rules]
    POL -->|allow| EXhome[Executor / forwarder]
    POL -->|needs approval| APR[Approval delivery<br/>human-in-the-loop]
    APR -->|approved| EXhome
    POL -->|deny| REJ[Reject + audit]
    API --> AUD[(Audit store<br/>Postgres)]
    EXhome --> AUD
    API -.->|DB unavailable| WAL[Degraded-mode<br/>local WAL queue]
    WAL -.->|replay on recovery| AUD
```

## Features

- **Unified dispatch surface** — every side-effect enters through one API instead of N ad-hoc channels.
- **Policy-as-data** — rules are evaluated by a hot-cached evaluator loaded from YAML; change policy without shipping code.
- **Human-in-the-loop gates** — high-impact actions pause for explicit approval with time-boxed one-tap approve/deny tokens.
- **Complete audit trail** — every request, decision, and outcome is persisted; the audit row is written whether the action is allowed, denied, or deferred.
- **Shadow mode** — SOL can observe and record without enforcing, so it can be introduced to a live system safely before it takes the wheel.
- **Degraded-mode durability** — if the database is unavailable, dispatches are queued to a local write-ahead log and replayed on recovery; the fleet keeps moving.
- **Layered auth** — short-lived JWTs for human admins, signed service tokens for agents, with a transport-security (mTLS) hardening path.
- **Observability built in** — Prometheus metrics and structured logging on every path.

## Quick start

```bash
git clone https://github.com/SurgeXi/surge-orchestrator.git
cd surge-orchestrator

python3.12 -m venv .venv && . .venv/bin/activate
pip install -e .[dev]

# Point at a Postgres database and apply migrations
export SOL_DATABASE_URL="postgresql+psycopg2://sol:sol@localhost:5432/sol"
alembic upgrade head

# Run in shadow mode: observe + audit, do not enforce
export SOL_ENFORCE=false
export SOL_SHADOW_ENABLED=true
uvicorn sol.main:app --host 127.0.0.1 --port 9320 --reload
```

Run the test suite:

```bash
pytest -q tests/unit
```

## Configuration

SOL is configured entirely through environment variables (see `.env.example`):

| Variable | Purpose |
|----------|---------|
| `SOL_DATABASE_URL` | Postgres connection string for the audit store |
| `SOL_ENFORCE` | `true` = block disallowed actions; `false` = observe only |
| `SOL_SHADOW_ENABLED` | Record dispatches without executing them |
| `SOL_ENVIRONMENT` | `dev` / `staging` / `prod` selectors for logging + policy |

Policy rules live in a YAML file loaded at startup and hot-reloaded into the
evaluator's cache; each rule maps a capability + context to an outcome
(`allow`, `deny`, or `require_approval`).

## Design notes

The central bet is a **narrow waist**. Agent platforms tend to grow several
parallel side-effect channels — a tool broker here, a permission check there, a
task runner somewhere else — and auditability erodes because no single component
sees everything. SOL deliberately funnels every consequential action through one
interface so that *policy, audit, and dispatch share one truth*.

Two decisions make that safe to adopt in a live system:

1. **Shadow-first rollout.** SOL can be wired in as a pure observer
   (`SOL_ENFORCE=false`). It writes the same audit rows it would in enforcing
   mode, so you can validate its decisions against reality before letting it
   block anything. The legacy channels stay primary until you're confident.
2. **Fail-open durability, not fail-silent.** A centralized control plane is a
   potential single point of failure. SOL answers that with a degraded mode:
   if Postgres is unavailable, dispatches are written to a local WAL and
   replayed on recovery, so a database blip never silently drops the audit
   trail or stalls the fleet.

Auth is deliberately layered by principal: agents authenticate with signed
service tokens, humans with short-lived JWTs, and one-tap approval links carry
their own tightly time-boxed tokens — a leaked approval link expires in minutes.

## Roadmap

- [ ] Enforcing mode on by default after the shadow-validation window
- [ ] mTLS for all service-to-service transport
- [ ] Admin UI for live policy editing and audit search
- [ ] Pluggable approval-delivery channels (chat, mobile push, email)

## License
© 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
Source-available for evaluation only — see LICENSE.

