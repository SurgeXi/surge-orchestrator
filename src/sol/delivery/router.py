"""Identity-aware approval-delivery router.

Single source of truth for the rule defined in
[[pulsepoint-design-decisions]] §5 — pick the approval-delivery
channel(s) based on the identity context carried with the dispatch:

  if context.identity.session_surface == "pulsepoint-chat":
      if context.identity.logged_in_user == "todd@surgexi.com":
          # operator monitoring → approval card inline in chat
          return ["pulsepoint_chat", "geopro", "email"]
      else:
          # customer in the seat → never prompt them
          return ["geopro", "email"]
  if context.actor.kind == "agent" and not capability.requires_human:
      # routine agent action, no human needed
      return ["log_only"]
  return ["geopro", "email"]

Phase 3 (task #107):
- Lives standalone so it can be unit-tested against both scenarios
  without a Postgres dependency.
- ``choose_channels_for_request()`` consumes the DispatchRequest
  schema directly so it can be wired into the approval-creation
  service in src/sol/services/approvals.py (currently introduced
  in PR #5 for Week 2 email delivery) with one line.
- ``choose_targets()`` returns (channel_name, target) pairs that the
  approvals service uses to invoke each DeliveryChannel.

Phase 3+ extensions (out of scope for this PR):
- Per-tenant ``geopro_target`` overrides driven by policy.yaml
- Capability-level routing overrides (e.g. money-movement always
  multi-channels regardless of identity)
- Multi-operator support (more than just Todd)

References:
  [[pulsepoint-design-decisions]] §5 — locked routing rule
  [[sol-buildable-spec]] §6 — channel priority list
  [[option-3-unified-surge-design]] §6 — channel selection logic
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from ..schemas.dispatch import DispatchRequest, Identity

# Canonical session_surface value PulsePoint widget + Brain set for
# chat-originated dispatches. Mirrors surge-brain/sol_identity.py.
PULSEPOINT_SESSION_SURFACE = "pulsepoint-chat"

# Operators whose presence in the chat seat means approvals surface
# inline (vs. a GEOpro card). Configurable so a future multi-operator
# deployment can list more usernames here without rewriting the
# router. Mirrors surge-brain/sol_identity.py.DEFAULT_OPERATOR_IDENTITIES.
DEFAULT_OPERATOR_IDENTITIES = frozenset({"todd@surgexi.com", "todd"})

# Default GEOpro recipient when an approval routes via GEOpro. The
# §5 spec says "send_to_geopro(target=todd)" by default — so unless the
# dispatch passes its own ``geopro_target`` (e.g. a partner-firm chat
# routing to the partner CPA), we send to Todd.
DEFAULT_GEOPRO_TARGET = "todd"


@dataclass(frozen=True)
class ChannelChoice:
    """A single (channel_name, target) pair the approvals service should attempt.

    ``target`` is channel-specific:
      - pulsepoint_chat: the PulsePoint session_id (resolved upstream)
      - geopro:          the GEOpro user identifier (default "todd")
      - email:           the resolved recipient email address
      - agent_monitor:   the operator console session/id
      - log_only:        a free-form tag for grep-ability
    """
    channel: str
    target: str


# Capability tier — used as a fallback when we don't have full
# capability metadata available. The router accepts it as an Optional
# kwarg so tests can drive the rule without a full Capability ORM row.
@dataclass(frozen=True)
class CapabilityHint:
    name: str
    requires_human: bool = True


def is_operator(logged_in_user: Optional[str]) -> bool:
    """True when the logged-in user is a known SurgeXi operator.

    Mirrors surge-brain ``sol_identity.SolIdentityContext.is_operator``.
    Case-insensitive on the email local-part because admins frequently
    type todd@... with mixed case.
    """
    if not logged_in_user:
        return False
    return logged_in_user.strip().lower() in {
        op.lower() for op in DEFAULT_OPERATOR_IDENTITIES
    }


def choose_channels(
    identity: Identity,
    *,
    actor_kind: str = "agent",
    capability: Optional[CapabilityHint] = None,
) -> list[str]:
    """Return the ordered channel list per identity + actor + capability.

    Spec §6 verbatim — the one place this rule lives.

    The order matters: SOL's delivery worker attempts each channel in
    order until one succeeds (per [[sol-buildable-spec]] §6 "Failure
    cascade"). Earlier entries are the *preferred* surface; later
    entries are durability fallbacks.

    Parameters
    ----------
    identity : Identity
        The SOL dispatch identity payload — what Brain stages from
        the PulsePoint header per ``sol_identity.from_headers()``.
    actor_kind : str
        "agent" or "human" — from ``context.actor.kind``. Used only
        for the routine-agent log-only case.
    capability : CapabilityHint | None
        Optional capability metadata. When set and
        ``requires_human=False``, a routine agent action gets log_only.
        Defaults to ``requires_human=True`` so the safer route wins
        when capability metadata is missing.
    """
    surface = (identity.session_surface or "").lower()
    user = (identity.logged_in_user or "")

    # § 5 routing rule — PulsePoint chat is the deciding surface.
    if surface == PULSEPOINT_SESSION_SURFACE:
        if is_operator(user):
            # Todd is monitoring → approval card surfaces in chat first.
            # GEOpro + email follow as durability fallbacks.
            return ["pulsepoint_chat", "geopro", "email"]
        # Customer in the seat — never prompt them. GEOpro is the
        # primary surface, email is the durability fallback.
        return ["geopro", "email"]

    # Routine, fully-auto agent actions: just log. Caller's
    # ``capability.requires_human`` opt-in is required.
    requires_human = capability.requires_human if capability else True
    if actor_kind == "agent" and not requires_human:
        return ["log_only"]

    # Default fallback for every other dispatch (non-pulsepoint,
    # human-required agent action, or human-initiated dispatch).
    return ["geopro", "email"]


def choose_targets(
    identity: Identity,
    *,
    actor_kind: str = "agent",
    capability: Optional[CapabilityHint] = None,
    pulsepoint_session_id: Optional[str] = None,
    operator_email: Optional[str] = None,
) -> list[ChannelChoice]:
    """Return (channel, target) pairs for the approval-creation service.

    Resolves channel name → concrete delivery target:
      pulsepoint_chat → ``pulsepoint_session_id`` (required for pulsepoint)
      geopro          → ``identity.geopro_target`` or DEFAULT_GEOPRO_TARGET
      email           → ``operator_email``
      agent_monitor   → ``identity.geopro_target`` or DEFAULT_GEOPRO_TARGET
      log_only        → ``identity.session_surface or "default"``

    Channels for which no target is resolvable are silently dropped —
    the caller still gets the remaining channels. This is the
    "skip channels we don't have configuration for" rule, e.g. when
    the deployment has no GEOpro endpoint yet (Phase 3 today), the
    router still returns email as the durability fallback.
    """
    channels = choose_channels(identity, actor_kind=actor_kind, capability=capability)
    geopro_target = (identity.geopro_target or DEFAULT_GEOPRO_TARGET).strip()
    pairs: list[ChannelChoice] = []
    for ch in channels:
        if ch == "pulsepoint_chat":
            if pulsepoint_session_id:
                pairs.append(ChannelChoice("pulsepoint_chat", pulsepoint_session_id))
        elif ch == "geopro":
            pairs.append(ChannelChoice("geopro", geopro_target or DEFAULT_GEOPRO_TARGET))
        elif ch == "email":
            if operator_email:
                pairs.append(ChannelChoice("email", operator_email))
        elif ch == "agent_monitor":
            pairs.append(ChannelChoice("agent_monitor", geopro_target or DEFAULT_GEOPRO_TARGET))
        elif ch == "log_only":
            pairs.append(ChannelChoice("log_only", identity.session_surface or "default"))
    if not pairs:
        # Last-resort: log_only always succeeds. Ensures we never lose
        # the audit record of an approval-needed event.
        pairs.append(ChannelChoice("log_only", "fallback"))
    return pairs


def choose_channels_for_request(payload: DispatchRequest) -> list[str]:
    """Convenience wrapper for the approvals service.

    Pulls identity + actor.kind out of a full DispatchRequest, ignores
    capability metadata for now (no Capability lookup at this seam).
    Approval-creation services with capability lookup should call
    ``choose_channels()`` directly with the full ``CapabilityHint``.
    """
    return choose_channels(
        payload.context.identity,
        actor_kind=payload.context.actor.kind,
    )


def channels_summary(channels: Iterable[str]) -> str:
    """Human-readable summary for audit logs."""
    return " > ".join(channels) or "(no channels)"
