# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Approval delivery channel protocol."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class DeliveryAttempt:
    channel: str
    target: str
    started_at: datetime
    succeeded: bool
    response: str | None = None


class DeliveryChannel(Protocol):
    name: str

    async def deliver(self, approval: dict, target: str) -> DeliveryAttempt: ...
