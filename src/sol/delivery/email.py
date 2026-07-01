# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""SMTP email delivery channel.

Phase 3.2 Week 2 — primary approval-delivery channel. Sends a MIME
multipart (text + HTML) message to each approver target, embedding two
short-lived signed one-tap URLs (approve / deny) that resolve to
``GET /v1/sol/approvals/{id}/decide?token=<signed>&decision=...``.

Configuration source of truth:
  /etc/pulse-engage/smtp.env-style env file (loaded into the systemd
  unit via EnvironmentFile=, or set in sol.service drop-in).

Env vars (all SOL_-prefixed inside SOL; the pulse-engage SMTP_* names
are mapped one-to-one in /etc/sol/smtp.env):

  SOL_SMTP_HOST          (default localhost)
  SOL_SMTP_PORT          (default 25)
  SOL_SMTP_USERNAME      (optional)
  SOL_SMTP_PASSWORD      (optional)
  SOL_SMTP_STARTTLS      (default false)
  SOL_SMTP_AUTH          (default false)
  SOL_SMTP_ENABLED       (default false — explicit opt-in)
  SOL_SMTP_FROM_ADDRESS  (default sol@surgexi.com)
  SOL_SMTP_FROM_NAME     (default "Surge Orchestration Layer")
  SOL_SMTP_TIMEOUT_SECONDS (default 10)
  SOL_CALLBACK_BASE_URL  (default https://sol.surgexi.com)

Failure semantics:
  - deliver() NEVER raises. On failure: log warning, return DeliveryAttempt
    with succeeded=False and a non-empty response string for the audit log.
  - SMTP_ENABLED=false → return a "disabled" attempt so the orchestrator
    can fall through to the next channel (ntfy / log_only).
"""
from __future__ import annotations

import asyncio
import smtplib
import ssl
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any
from urllib.parse import quote

from ..auth.callback_tokens import issue as issue_callback_token
from ..observability.logging import get_logger
from ..settings import get_settings
from .base import DeliveryAttempt

log = get_logger(__name__)


def _build_decide_url(approval_id: uuid.UUID, decision: str, base_url: str) -> str:
    token = issue_callback_token(approval_id, decision)
    return f"{base_url.rstrip('/')}/v1/sol/approvals/{approval_id}/decide?token={quote(token)}&decision={decision}"


def _summarize_args(args_json: dict[str, Any]) -> str:
    """Best-effort one-line summary of the action args for email subject + body."""
    if not args_json:
        return ""
    parts: list[str] = []
    for key in ("target", "tool", "cmd", "path", "host", "url"):
        v = args_json.get(key)
        if isinstance(v, str) and v:
            parts.append(f"{key}={v[:80]}")
    if parts:
        return " ".join(parts)
    keys = list(args_json.keys())[:3]
    return ", ".join(keys)


def _render(approval: dict[str, Any], approve_url: str, deny_url: str) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for the approval email."""
    cap = approval.get("capability") or "(unknown capability)"
    tenant = approval.get("tenant_id") or "system"
    actor = approval.get("actor_id") or "?"
    intent = approval.get("intent") or "(no intent provided)"
    args_summary = _summarize_args(approval.get("args_json") or {})
    expires_at = approval.get("expires_at")
    approval_id = approval.get("id")

    subject = f"[SOL] Approval needed: {cap} ({tenant})"
    text = (
        f"Surge Orchestration Layer is asking for your decision.\n\n"
        f"Capability : {cap}\n"
        f"Tenant     : {tenant}\n"
        f"Actor      : {actor}\n"
        f"Intent     : {intent}\n"
        f"Args       : {args_summary}\n"
        f"Approval   : {approval_id}\n"
        f"Expires at : {expires_at}\n\n"
        f"Approve : {approve_url}\n"
        f"Deny    : {deny_url}\n\n"
        f"Either link is single-use and short-lived. If you weren't expecting this\n"
        f"request, click Deny.\n"
    )
    html = f"""<!doctype html>
<html><body style="font-family: -apple-system,Segoe UI,sans-serif; color:#222; max-width:560px;">
<h2 style="margin:0 0 8px 0;">Approval requested</h2>
<p style="margin:0 0 16px 0; color:#555;">Surge Orchestration Layer is asking for your decision.</p>
<table cellpadding="4" style="border-collapse:collapse;font-size:14px;">
  <tr><td style="color:#888;">Capability</td><td><code>{cap}</code></td></tr>
  <tr><td style="color:#888;">Tenant</td><td>{tenant}</td></tr>
  <tr><td style="color:#888;">Actor</td><td>{actor}</td></tr>
  <tr><td style="color:#888;">Intent</td><td>{intent}</td></tr>
  <tr><td style="color:#888;">Args</td><td><code>{args_summary}</code></td></tr>
  <tr><td style="color:#888;">Approval</td><td><code>{approval_id}</code></td></tr>
  <tr><td style="color:#888;">Expires</td><td>{expires_at}</td></tr>
</table>
<p style="margin:18px 0;">
  <a href="{approve_url}" style="background:#137333;color:#fff;padding:10px 18px;text-decoration:none;border-radius:6px;margin-right:8px;">Approve</a>
  <a href="{deny_url}" style="background:#a50e0e;color:#fff;padding:10px 18px;text-decoration:none;border-radius:6px;">Deny</a>
</p>
<p style="font-size:12px;color:#888;">Each link is single-use and expires in 15 min. If you didn't expect this, click Deny.</p>
</body></html>"""
    return subject, text, html


def _send_smtp_sync(message: EmailMessage) -> tuple[bool, str]:
    """Blocking SMTP send. Returns (succeeded, response_str). Never raises."""
    s = get_settings()
    try:
        if s.smtp_starttls:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                if s.smtp_auth and s.smtp_username and s.smtp_password:
                    smtp.login(s.smtp_username, s.smtp_password)
                refused = smtp.send_message(message)
                if refused:
                    return False, f"refused:{refused}"
                return True, "sent"
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds) as smtp:
                if s.smtp_auth and s.smtp_username and s.smtp_password:
                    smtp.login(s.smtp_username, s.smtp_password)
                refused = smtp.send_message(message)
                if refused:
                    return False, f"refused:{refused}"
                return True, "sent"
    except Exception as e:  # pragma: no cover — smtp errors are integration-only
        return False, f"{type(e).__name__}:{e}"


class EmailDelivery:
    name = "email"

    async def deliver(self, approval: dict[str, Any], target: str) -> DeliveryAttempt:
        started = datetime.now(UTC)
        s = get_settings()
        if not s.smtp_enabled:
            log.info(
                "sol.delivery.email.disabled",
                approval_id=str(approval.get("id")),
                target=target,
            )
            return DeliveryAttempt(
                channel=self.name,
                target=target,
                started_at=started,
                succeeded=False,
                response="smtp_disabled",
            )
        if "@" not in (target or ""):
            return DeliveryAttempt(
                channel=self.name,
                target=target,
                started_at=started,
                succeeded=False,
                response="invalid_email_target",
            )

        approval_id = approval["id"] if isinstance(approval.get("id"), uuid.UUID) else uuid.UUID(str(approval.get("id")))
        approve_url = _build_decide_url(approval_id, "approve", s.callback_base_url)
        deny_url = _build_decide_url(approval_id, "deny", s.callback_base_url)

        subject, text_body, html_body = _render(approval, approve_url, deny_url)

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr((s.smtp_from_name, s.smtp_from_address))
        msg["To"] = target
        msg["Message-ID"] = make_msgid(domain=s.smtp_from_address.split("@", 1)[-1] or "surgexi.com")
        msg["X-SOL-Approval-Id"] = str(approval_id)
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")

        succeeded, response = await asyncio.to_thread(_send_smtp_sync, msg)

        log.info(
            "sol.delivery.email" if succeeded else "sol.delivery.email.failed",
            approval_id=str(approval_id),
            target=target,
            succeeded=succeeded,
            response=response[:200],
        )
        return DeliveryAttempt(
            channel=self.name,
            target=target,
            started_at=started,
            succeeded=succeeded,
            response=response,
        )
