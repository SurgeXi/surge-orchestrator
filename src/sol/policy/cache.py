"""In-memory hot policy cache (refreshed from YAML + DB)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class HotPolicy:
    version: int
    rules: list[dict]
    expiry_defaults: dict[str, int] = field(default_factory=dict)


class PolicyCache:
    def __init__(self) -> None:
        self._policy: HotPolicy | None = None

    @property
    def is_loaded(self) -> bool:
        return self._policy is not None

    @property
    def current(self) -> HotPolicy | None:
        return self._policy

    def load_from_yaml(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            # Phase 3.1 — file may not exist on first deploy; load empty default.
            self._policy = HotPolicy(version=0, rules=[], expiry_defaults=_DEFAULT_EXPIRY)
            return
        data = yaml.safe_load(p.read_text()) or {}
        self._policy = HotPolicy(
            version=int(data.get("version", 0)),
            rules=list(data.get("rules", [])),
            expiry_defaults={**_DEFAULT_EXPIRY, **(data.get("expiry_defaults") or {})},
        )

    def expiry_for(self, capability: str, category: str | None = None) -> int:
        if self._policy is None:
            return _DEFAULT_EXPIRY["standard"]
        defaults = self._policy.expiry_defaults
        if category and category in defaults:
            return defaults[category]
        return defaults.get("standard", _DEFAULT_EXPIRY["standard"])


# Per spec §10 #7 — per-capability expiry defaults.
_DEFAULT_EXPIRY: dict[str, int] = {
    "money": 4 * 3600,           # 4h
    "tenant": 8 * 3600,          # 8h
    "standard": 24 * 3600,       # 24h
    "onboarding": 72 * 3600,     # 72h
    "read_only": 1 * 3600,       # 1h
}
