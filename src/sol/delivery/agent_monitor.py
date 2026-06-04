"""Agent-monitor (operator console) delivery (Phase 3 follow-up)."""
from __future__ import annotations

from datetime import UTC, datetime

from .base import DeliveryAttempt


class AgentMonitorDelivery:
    name = "agent_monitor"

    async def deliver(self, approval: dict, target: str) -> DeliveryAttempt:
        return DeliveryAttempt(
            channel=self.name,
            target=target,
            started_at=datetime.now(UTC),
            succeeded=False,
            response="not_implemented_week1",
        )
