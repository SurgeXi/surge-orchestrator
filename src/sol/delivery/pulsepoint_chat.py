"""PulsePoint chat delivery (full implementation Phase 3 per spec §10 #6)."""
from __future__ import annotations

from datetime import UTC, datetime

from .base import DeliveryAttempt


class PulsePointChatDelivery:
    name = "pulsepoint_chat"

    async def deliver(self, approval: dict, target: str) -> DeliveryAttempt:
        return DeliveryAttempt(
            channel=self.name,
            target=target,
            started_at=datetime.now(UTC),
            succeeded=False,
            response="not_implemented_week1",
        )
