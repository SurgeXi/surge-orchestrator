# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""policy.yaml loader (kept separate from the cache for testability)."""
from __future__ import annotations

from pathlib import Path

import yaml


def load_yaml(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}
