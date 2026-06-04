"""GEOpro card delivery (full implementation lands Week 6 cutover)."""
from __future__ import annotations

from datetime import UTC, datetime

from .base import DeliveryAttempt


class GeoproDelivery:
    name = "geopro"

    async def deliver(self, approval: dict, target: str) -> DeliveryAttempt:
        return DeliveryAttempt(
            channel=self.name,
            target=target,
            started_at=datetime.now(UTC),
            succeeded=False,
            response="not_implemented_week1",
        )
