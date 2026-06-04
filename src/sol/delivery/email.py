"""SMTP email delivery (full implementation lands Week 2)."""
from __future__ import annotations

from datetime import UTC, datetime

from .base import DeliveryAttempt


class EmailDelivery:
    name = "email"

    async def deliver(self, approval: dict, target: str) -> DeliveryAttempt:
        return DeliveryAttempt(
            channel=self.name,
            target=target,
            started_at=datetime.now(UTC),
            succeeded=False,
            response="not_implemented_week1",
        )
