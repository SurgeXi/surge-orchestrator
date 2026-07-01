# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Local append-only WAL queue (Postgres-down fallback). Full impl Week 6."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path


def append_wal(wal_dir: str, entry: dict) -> None:
    p = Path(wal_dir)
    p.mkdir(parents=True, exist_ok=True)
    fname = datetime.now(UTC).strftime("%Y%m%d.log")
    target = p / fname
    line = json.dumps({"ts": datetime.now(UTC).isoformat(), **entry})
    with open(target, "a", buffering=1) as f:
        f.write(line + "\n")
    os.chmod(target, 0o640)
