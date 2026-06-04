"""Log-only delivery — terminal fallback that always succeeds."""
from __future__ import annotations

from datetime import UTC, datetime

from ..observability.logging import get_logger
from .base import DeliveryAttempt

log = get_logger(__name__)


class LogOnlyDelivery:
    name = "log_only"

    async def deliver(self, approval: dict, target: str) -> DeliveryAttempt:
        log.warning(
            "sol.delivery.log_only",
            approval_id=str(approval.get("id")),
            tenant=approval.get("tenant_id"),
            actor=approval.get("actor_id"),
            capability=approval.get("capability"),
            target=target,
        )
        return DeliveryAttempt(
            channel=self.name,
            target=target,
            started_at=datetime.now(UTC),
            succeeded=True,
            response="logged",
        )
