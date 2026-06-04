"""Cross-rule policy evaluators — Phase 3.4.

Cross-rules are constraints that span MULTIPLE dispatches and therefore
can't be evaluated against a single ``DispatchRequest`` in isolation.
They look at recent ``sol.dispatches`` history to decide.

First rule shipped: ``repo_cooldown`` — "no two surge-runner dispatches
on the same repo within N seconds" (default 300s / 5min).

The rule reads ``args.metadata.repo`` (canonical) or ``args.repo``
(fallback) to identify the repo, scoped by tenant_id. The cooldown
window is configurable per-rule in /etc/sol/policy.yaml under:

    cross_rules:
      repo_cooldown:
        capabilities: [surge_runner_dispatch, surge_runner_task]
        window_seconds: 300
        reason: "repo_cooldown: <repo> dispatched <Ns> ago"
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..models import Dispatch
from .cache import PolicyCache


@dataclass
class CrossRuleResult:
    allowed: bool
    rule: str | None = None
    reason: str | None = None


def _extract_repo(args: dict[str, Any]) -> str | None:
    """Return a normalized repo identifier or None."""
    meta = args.get("metadata") if isinstance(args, dict) else None
    if isinstance(meta, dict):
        repo = meta.get("repo")
        if repo:
            return str(repo).strip().lower() or None
    if isinstance(args, dict):
        repo = args.get("repo")
        if repo:
            return str(repo).strip().lower() or None
    return None


def _repo_cooldown_config(cache: PolicyCache) -> dict[str, Any] | None:
    if cache is None or cache.current is None:
        return None
    raw = getattr(cache.current, "cross_rules", None) or {}
    cfg = raw.get("repo_cooldown") if isinstance(raw, dict) else None
    if not isinstance(cfg, dict):
        return None
    return cfg


def evaluate_repo_cooldown(
    *,
    db: Session,
    capability: str,
    tenant_id: str,
    args: dict[str, Any],
    cache: PolicyCache,
    now: datetime | None = None,
) -> CrossRuleResult:
    """Deny if another auto/human-approved dispatch for the same repo
    happened inside the configured window.

    Counts dispatches whose ``decision`` is ``approved`` or ``executed``
    (i.e. the executor would have run). Shadow rows do NOT count —
    shadow audits are observational. Denied/queued/timed-out rows also
    do not count because no executor was triggered.
    """
    cfg = _repo_cooldown_config(cache)
    if cfg is None:
        return CrossRuleResult(allowed=True)

    caps = cfg.get("capabilities") or ["surge_runner_dispatch"]
    if capability not in caps:
        return CrossRuleResult(allowed=True)

    repo = _extract_repo(args)
    if repo is None:
        # Rule only applies when we can identify a repo. No repo → allow.
        return CrossRuleResult(allowed=True)

    try:
        window = int(cfg.get("window_seconds", 300))
    except (TypeError, ValueError):
        window = 300
    window = max(1, window)

    now_ts = now or datetime.now(UTC)
    cutoff = now_ts - timedelta(seconds=window)

    stmt = (
        select(Dispatch)
        .where(
            and_(
                Dispatch.capability.in_(caps),
                Dispatch.tenant_id == tenant_id,
                Dispatch.decision.in_(("approved", "executed")),
                Dispatch.created_at >= cutoff,
            )
        )
        .order_by(Dispatch.created_at.desc())
        .limit(50)
    )
    rows = db.execute(stmt).scalars().all()

    for row in rows:
        prior_repo = _extract_repo(row.args_json or {})
        if prior_repo == repo:
            elapsed = max(0, int((now_ts - row.created_at).total_seconds()))
            reason_tmpl = cfg.get("reason") or (
                "repo_cooldown: {repo} dispatched {elapsed}s ago "
                "(cooldown {window}s)"
            )
            reason = reason_tmpl.format(
                repo=repo, elapsed=elapsed, window=window
            )
            return CrossRuleResult(
                allowed=False,
                rule="repo_cooldown",
                reason=reason,
            )

    return CrossRuleResult(allowed=True)
