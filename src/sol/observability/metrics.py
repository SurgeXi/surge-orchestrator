"""Prometheus metric definitions (spec §7)."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

dispatches_total = Counter(
    "sol_dispatches_total",
    "Total dispatches received.",
    ["tenant", "capability", "decision"],
)
dispatch_latency_seconds = Histogram(
    "sol_dispatch_latency_seconds",
    "End-to-end dispatch latency (decision only; excludes executor RT).",
    ["tenant", "capability"],
)
approvals_pending = Gauge(
    "sol_approvals_pending",
    "Approvals currently in pending state.",
    ["tenant"],
)
approvals_decided_total = Counter(
    "sol_approvals_decided_total",
    "Approvals decided by humans.",
    ["tenant", "decision"],
)
approval_decision_latency_seconds = Histogram(
    "sol_approval_decision_latency_seconds",
    "Time from approval creation to human decision.",
    ["tenant"],
)
policy_violations_total = Counter(
    "sol_policy_violations_total",
    "Cross-rule policy violations.",
    ["rule_id", "tenant"],
)
delivery_attempts_total = Counter(
    "sol_delivery_attempts_total",
    "Approval delivery attempts.",
    ["channel", "result"],
)
capabilities_active = Gauge(
    "sol_capabilities_active",
    "Number of capabilities with status=active.",
)
fallback_total = Counter(
    "sol_fallback_total",
    "Number of fallback/degraded-mode events.",
    ["from_path"],
)
db_up = Gauge(
    "sol_db_up",
    "Postgres reachable (0/1).",
)


def init_metrics() -> None:
    """Module import suffices to register; this hook exists for explicit lifespan call."""
    db_up.set(0)
