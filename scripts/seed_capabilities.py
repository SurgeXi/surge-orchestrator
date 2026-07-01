# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Seed sol.capabilities with the Week-1 baseline set.

Run on surgecore after migrations:
    SOL_DATABASE_URL=postgresql+psycopg2://... python scripts/seed_capabilities.py
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from sol.db import get_session_factory
from sol.models import Capability

# 4 existing low-level adapters (from /opt/claw/adapters/) + 3 high-level channels
SEED = [
    # adapters
    {
        "name": "docker_exec",
        "owner_service": "claw_core",
        "min_tier": 2,
        "handler_kind": "permission_gate",
        "handler_endpoint": "/opt/claw/adapters/docker_exec.sh",
        "args_schema_json": {
            "type": "object",
            "required": ["container", "cmd"],
            "properties": {"container": {"type": "string"}, "cmd": {"type": "string"}},
        },
        "description": "docker exec <container> sh -c <cmd>",
        "requires_human": True,
        "expiry_seconds": 24 * 3600,
    },
    {
        "name": "ssh_exec",
        "owner_service": "claw_core",
        "min_tier": 2,
        "handler_kind": "permission_gate",
        "handler_endpoint": "/opt/claw/adapters/ssh_exec.sh",
        "args_schema_json": {
            "type": "object",
            "required": ["host", "cmd"],
            "properties": {"host": {"type": "string"}, "cmd": {"type": "string"}},
        },
        "description": "SSH to host in hosts.json + per-host allow_regex",
        "requires_human": True,
        "expiry_seconds": 24 * 3600,
    },
    {
        "name": "mac",
        "owner_service": "claw_core",
        "min_tier": 2,
        "handler_kind": "permission_gate",
        "handler_endpoint": "/opt/claw/adapters/mac.sh",
        "args_schema_json": {
            "type": "object",
            "required": ["cmd"],
            "properties": {"cmd": {"type": "string"}},
        },
        "description": "Mac mini gateway (ping, whoami only)",
        "requires_human": True,
        "expiry_seconds": 24 * 3600,
    },
    {
        "name": "printer",
        "owner_service": "claw_core",
        "min_tier": 1,
        "handler_kind": "permission_gate",
        "handler_endpoint": "/opt/claw/adapters/printer.sh",
        "args_schema_json": {"type": "object", "properties": {}},
        "description": "HP printer placeholder",
        "requires_human": False,
        "expiry_seconds": 24 * 3600,
    },
    # high-level channels (the 3 Brain channels per project_brain_control_plane_architecture)
    {
        "name": "broker_capability",
        "owner_service": "brain",
        "min_tier": 1,
        "handler_kind": "broker",
        "handler_endpoint": "http://127.0.0.1:8220",
        "args_schema_json": {
            "type": "object",
            "required": ["capability", "params"],
            "properties": {
                "capability": {"type": "string"},
                "params": {"type": "object"},
            },
        },
        "description": "Maestro broker capability call (camera, geo, db_query)",
        "requires_human": True,
        "expiry_seconds": 24 * 3600,
    },
    {
        "name": "permission_gate_op",
        "owner_service": "brain",
        "min_tier": 2,
        "handler_kind": "permission_gate",
        "handler_endpoint": "/opt/surgexi/brain/permission_gate.py",
        "args_schema_json": {
            "type": "object",
            "required": ["tool", "args"],
            "properties": {
                "tool": {
                    "type": "string",
                    "enum": ["write_file", "edit_file", "run_bash", "ssh_remote"],
                },
                "args": {"type": "object"},
            },
        },
        "description": "Brain low-level host ops via permission_gate.enqueue()",
        "requires_human": True,
        "expiry_seconds": 24 * 3600,
    },
    {
        "name": "surge_runner_task",
        "owner_service": "brain",
        "min_tier": 2,
        "handler_kind": "surge_runner",
        "handler_endpoint": "http://100.107.52.93:9100/tasks",
        "args_schema_json": {
            "type": "object",
            "required": ["repo", "issue", "prompt"],
            "properties": {
                "repo": {"type": "string"},
                "issue": {"type": ["integer", "string"]},
                "prompt": {"type": "string"},
            },
        },
        "description": "Surge Runner autonomous GitHub-issue dispatch",
        "requires_human": True,
        "expiry_seconds": 24 * 3600,
    },
]


def seed() -> int:
    factory = get_session_factory()
    db = factory()
    now = datetime.now(UTC)
    n = 0
    try:
        for cap in SEED:
            stmt = pg_insert(Capability).values(
                **cap,
                last_registered_at=now,
                status="active",
            ).on_conflict_do_update(
                index_elements=["name"],
                set_={
                    "owner_service": cap["owner_service"],
                    "min_tier": cap["min_tier"],
                    "handler_kind": cap["handler_kind"],
                    "handler_endpoint": cap["handler_endpoint"],
                    "args_schema_json": cap["args_schema_json"],
                    "description": cap["description"],
                    "requires_human": cap["requires_human"],
                    "expiry_seconds": cap["expiry_seconds"],
                    "last_registered_at": now,
                    "status": "active",
                },
            )
            db.execute(stmt)
            n += 1
        db.commit()
    finally:
        db.close()
    return n


if __name__ == "__main__":
    n = seed()
    print(f"seeded {n} capabilities")
