"""Policy evaluator (skeleton — full eval lands Week 2)."""
from __future__ import annotations

from dataclasses import dataclass

from ..schemas.dispatch import DispatchRequest
from .cache import PolicyCache


@dataclass
class PolicyDecision:
    decision: str        # "approve" | "deny" | "queue" | "escalate"
    decision_path: str   # "auto-policy" | "human-approval" | etc.
    reason: str | None = None


def evaluate(req: DispatchRequest, cache: PolicyCache) -> PolicyDecision:
    """Skeleton evaluator. Week 1 returns auto-approve; Week 2 introduces real rules."""
    return PolicyDecision(
        decision="approve",
        decision_path="auto-policy",
        reason="skeleton-allow-all",
    )
