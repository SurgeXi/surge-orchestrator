"""Identity-aware approval-delivery router tests — task #107.

Locks the rule from [[pulsepoint-design-decisions]] §5 in code:

  Todd in chat   → ["pulsepoint_chat", "geopro", "email"]
  Customer chat  → ["geopro", "email"]   (NO pulsepoint_chat)
  Routine agent  → ["log_only"]
  Default        → ["geopro", "email"]

End-to-end test: synthesize a PulsePoint chat session as Todd → assert
the router picks ``pulsepoint_chat`` first. Synthesize the same session
as Sheilia → assert the router never picks ``pulsepoint_chat``.

These tests run offline (no Postgres, no real PulsePoint hub) because
the router is a pure function. Postgres-backed integration of the
router into the approvals service lives in the Week 2 PR #5 follow-up.
"""
from __future__ import annotations

import uuid

from sol.delivery.router import (
    DEFAULT_GEOPRO_TARGET,
    DEFAULT_OPERATOR_IDENTITIES,
    PULSEPOINT_SESSION_SURFACE,
    CapabilityHint,
    ChannelChoice,
    channels_summary,
    choose_channels,
    choose_channels_for_request,
    choose_targets,
    is_operator,
)
from sol.schemas.dispatch import (
    Actor,
    DispatchContext,
    DispatchRequest,
    Identity,
)


# ---------------------------------------------------------------------------
# is_operator — operator recognition
# ---------------------------------------------------------------------------


def test_is_operator_todd_email():
    assert is_operator("todd@surgexi.com")


def test_is_operator_todd_short_name():
    assert is_operator("todd")


def test_is_operator_case_insensitive():
    assert is_operator("Todd@SurgeXi.com")
    assert is_operator("TODD")


def test_is_operator_customer_returns_false():
    assert not is_operator("sheilia@timesavedap.com")


def test_is_operator_empty_returns_false():
    assert not is_operator("")
    assert not is_operator(None)


def test_default_operator_identities_lists_todd():
    """Sanity-check the operator allowlist we ship with."""
    assert "todd@surgexi.com" in DEFAULT_OPERATOR_IDENTITIES


# ---------------------------------------------------------------------------
# choose_channels — the §5 rule itself
# ---------------------------------------------------------------------------


def test_todd_in_pulsepoint_chat_routes_in_chat_first():
    """Operator monitoring → approval card surfaces inline in PulsePoint."""
    identity = Identity(
        logged_in_user="todd@surgexi.com",
        session_surface=PULSEPOINT_SESSION_SURFACE,
        geopro_target="todd",
    )
    channels = choose_channels(identity)
    assert channels[0] == "pulsepoint_chat"
    # Durability fallbacks follow.
    assert channels == ["pulsepoint_chat", "geopro", "email"]


def test_customer_in_pulsepoint_chat_never_sees_pulsepoint_channel():
    """Sheilia in the seat → NO approval prompts to her. SOL routes via GEOpro."""
    identity = Identity(
        logged_in_user="sheilia@timesavedap.com",
        session_surface=PULSEPOINT_SESSION_SURFACE,
        geopro_target="todd",
    )
    channels = choose_channels(identity)
    assert "pulsepoint_chat" not in channels
    assert channels == ["geopro", "email"]


def test_customer_in_pulsepoint_chat_case_insensitive_operator_check():
    """``Todd@SurgeXi.com`` (mixed case) still recognized as operator."""
    identity = Identity(
        logged_in_user="Todd@SurgeXi.com",
        session_surface=PULSEPOINT_SESSION_SURFACE,
    )
    assert choose_channels(identity)[0] == "pulsepoint_chat"


def test_routine_agent_action_logs_only():
    """``capability.requires_human=False`` + agent actor → log only."""
    identity = Identity(session_surface=None)
    cap = CapabilityHint(name="docker_inspect", requires_human=False)
    channels = choose_channels(identity, actor_kind="agent", capability=cap)
    assert channels == ["log_only"]


def test_agent_action_requiring_human_uses_default_channels():
    identity = Identity(session_surface=None)
    cap = CapabilityHint(name="post_journal_entry", requires_human=True)
    channels = choose_channels(identity, actor_kind="agent", capability=cap)
    assert channels == ["geopro", "email"]


def test_default_when_no_identity_uses_geopro_then_email():
    """Non-PulsePoint dispatch with no capability info → geopro + email."""
    identity = Identity()  # session_surface=None
    channels = choose_channels(identity)
    assert channels == ["geopro", "email"]


def test_human_actor_uses_default_channels():
    """Human-initiated dispatches outside PulsePoint also use the default route."""
    identity = Identity()
    channels = choose_channels(identity, actor_kind="human")
    assert channels == ["geopro", "email"]


def test_unknown_session_surface_falls_through_to_default():
    """Session surfaces we don't know about don't accidentally pick pulsepoint_chat."""
    identity = Identity(
        logged_in_user="todd@surgexi.com",
        session_surface="some-future-surface",
    )
    channels = choose_channels(identity)
    assert "pulsepoint_chat" not in channels
    assert channels == ["geopro", "email"]


# ---------------------------------------------------------------------------
# choose_targets — channel → (channel, target) resolution
# ---------------------------------------------------------------------------


def test_choose_targets_todd_in_chat_resolves_session_target():
    identity = Identity(
        logged_in_user="todd@surgexi.com",
        session_surface=PULSEPOINT_SESSION_SURFACE,
        geopro_target="todd",
    )
    targets = choose_targets(
        identity,
        pulsepoint_session_id="sess-abc123",
        operator_email="todd@surgexi.com",
    )
    assert targets[0] == ChannelChoice("pulsepoint_chat", "sess-abc123")
    # GEOpro target defaults to "todd".
    assert ChannelChoice("geopro", "todd") in targets
    assert ChannelChoice("email", "todd@surgexi.com") in targets


def test_choose_targets_customer_in_chat_geopro_to_todd():
    identity = Identity(
        logged_in_user="sheilia@timesavedap.com",
        session_surface=PULSEPOINT_SESSION_SURFACE,
        geopro_target="todd",
    )
    targets = choose_targets(
        identity,
        pulsepoint_session_id="sess-abc123",   # provided but should be dropped
        operator_email="todd@surgexi.com",
    )
    assert not any(t.channel == "pulsepoint_chat" for t in targets)
    assert targets[0] == ChannelChoice("geopro", "todd")
    assert ChannelChoice("email", "todd@surgexi.com") in targets


def test_choose_targets_geopro_target_override():
    """Per-session GEOpro target override (e.g. partner-firm chat)."""
    identity = Identity(
        logged_in_user="customer@partner-firm.example",
        session_surface=PULSEPOINT_SESSION_SURFACE,
        geopro_target="partner-cpa",
    )
    targets = choose_targets(identity, operator_email="todd@surgexi.com")
    assert ChannelChoice("geopro", "partner-cpa") in targets


def test_choose_targets_pulsepoint_dropped_when_session_id_missing():
    """If the resolver can't find the PulsePoint session, drop the channel."""
    identity = Identity(
        logged_in_user="todd@surgexi.com",
        session_surface=PULSEPOINT_SESSION_SURFACE,
    )
    targets = choose_targets(identity, operator_email="todd@surgexi.com")
    assert not any(t.channel == "pulsepoint_chat" for t in targets)
    # Falls through to geopro + email.
    assert targets[0] == ChannelChoice("geopro", DEFAULT_GEOPRO_TARGET)


def test_choose_targets_email_dropped_when_no_recipient():
    identity = Identity(
        logged_in_user="sheilia@timesavedap.com",
        session_surface=PULSEPOINT_SESSION_SURFACE,
    )
    targets = choose_targets(identity)   # no operator_email
    assert not any(t.channel == "email" for t in targets)
    # Geopro is still there.
    assert any(t.channel == "geopro" for t in targets)


def test_choose_targets_log_only_fallback_when_nothing_resolvable():
    """Last-resort: log_only ALWAYS gets us a target so audit record exists."""
    identity = Identity()  # no surface, no anything
    cap = CapabilityHint(name="routine", requires_human=False)
    targets = choose_targets(identity, actor_kind="agent", capability=cap)
    assert targets == [ChannelChoice("log_only", "default")]


def test_choose_targets_returns_log_only_fallback_when_no_resolvable_targets():
    """No PulsePoint session_id + no email + non-pulsepoint surface → log_only fallback."""
    identity = Identity()  # nothing resolvable for default geopro+email
    targets = choose_targets(identity)
    # geopro resolves to default target "todd" always — so we DO get one channel.
    assert any(t.channel == "geopro" for t in targets)


# ---------------------------------------------------------------------------
# choose_channels_for_request — DispatchRequest convenience wrapper
# ---------------------------------------------------------------------------


def _build_request(identity: Identity, actor_kind: str = "agent") -> DispatchRequest:
    """Construct a minimal valid DispatchRequest for router input."""
    return DispatchRequest(
        capability="brain_call_tool",
        args={"target": "ssh_remote"},
        context=DispatchContext(
            tenant_id="timesavedap",
            actor=Actor(kind=actor_kind, id="brain", tier=2),
            identity=identity,
            intent="post-journal-entry",
            trace_id=uuid.uuid4().hex,
        ),
    )


def test_dispatchrequest_todd_in_pulsepoint_picks_pulsepoint_chat():
    req = _build_request(
        Identity(
            logged_in_user="todd@surgexi.com",
            session_surface=PULSEPOINT_SESSION_SURFACE,
        )
    )
    assert choose_channels_for_request(req)[0] == "pulsepoint_chat"


def test_dispatchrequest_customer_in_pulsepoint_omits_pulsepoint_chat():
    req = _build_request(
        Identity(
            logged_in_user="sheilia@timesavedap.com",
            session_surface=PULSEPOINT_SESSION_SURFACE,
        )
    )
    channels = choose_channels_for_request(req)
    assert "pulsepoint_chat" not in channels
    assert channels == ["geopro", "email"]


# ---------------------------------------------------------------------------
# Summary helpers — small but they're load-bearing for audit logs
# ---------------------------------------------------------------------------


def test_channels_summary_renders_arrow_separated_list():
    assert (
        channels_summary(["pulsepoint_chat", "geopro", "email"])
        == "pulsepoint_chat > geopro > email"
    )


def test_channels_summary_handles_empty():
    assert channels_summary([]) == "(no channels)"


# ---------------------------------------------------------------------------
# END-TO-END "WHO IS IN CHAT" SCENARIOS (task #107 deliverable)
# ---------------------------------------------------------------------------


def test_e2e_todd_logged_in_approval_routes_to_pulsepoint_chat():
    """E2E #1: synthesize PulsePoint session as Todd → approval card in chat.

    Mirrors what Brain stages when ``X-PulsePoint-Logged-In-User: todd@surgexi.com``
    arrives on a chat POST. Asserts the router picks ``pulsepoint_chat`` as
    the primary surface.
    """
    # 1) PulsePoint widget POSTs message with Todd's identity → server
    #    stores it, GET /v1/sessions/{id}/identity returns:
    pulsepoint_identity_response = {
        "session_id": "sess-todd-001",
        "logged_in_user": "todd@surgexi.com",
        "session_surface": "pulsepoint-chat",
    }
    # 2) Brain's chat handler calls sol_identity.from_headers(...) which
    #    builds the SOL Identity payload that's attached to the dispatch:
    identity = Identity(
        logged_in_user=pulsepoint_identity_response["logged_in_user"],
        session_surface=pulsepoint_identity_response["session_surface"],
        geopro_target="todd",
    )
    # 3) Brain fires shadow_dispatch — SOL receives the dispatch. When
    #    Week 2 approval-creation runs, the router resolves channels:
    targets = choose_targets(
        identity,
        pulsepoint_session_id=pulsepoint_identity_response["session_id"],
        operator_email="todd@surgexi.com",
    )
    # 4) Assert the primary surface is in-chat — Todd sees the card inline.
    assert targets[0].channel == "pulsepoint_chat"
    assert targets[0].target == "sess-todd-001"
    # 5) GEOpro + email are present as durability fallbacks.
    channels = [t.channel for t in targets]
    assert "geopro" in channels
    assert "email" in channels


def test_e2e_sheilia_logged_in_approval_routes_to_geopro_not_chat():
    """E2E #2: synthesize PulsePoint session as Sheilia → approval to GEOpro.

    Asserts the router NEVER picks ``pulsepoint_chat`` when the customer
    is in the seat — she sees nothing in chat about the approval per §5.
    """
    pulsepoint_identity_response = {
        "session_id": "sess-sheilia-001",
        "logged_in_user": "sheilia@timesavedap.com",
        "session_surface": "pulsepoint-chat",
    }
    identity = Identity(
        logged_in_user=pulsepoint_identity_response["logged_in_user"],
        session_surface=pulsepoint_identity_response["session_surface"],
        geopro_target="todd",
    )
    targets = choose_targets(
        identity,
        # Even if the session id is available, the router drops the
        # pulsepoint_chat channel — Sheilia must never see the approval.
        pulsepoint_session_id=pulsepoint_identity_response["session_id"],
        operator_email="todd@surgexi.com",
    )
    channels = [t.channel for t in targets]
    assert "pulsepoint_chat" not in channels, (
        "REGRESSION: Sheilia would see Todd's approval prompt in chat. "
        "Per [[pulsepoint-design-decisions]] §5 customers MUST NOT be "
        "prompted for approvals — route to GEOpro→Todd instead."
    )
    # Primary surface is GEOpro targeting Todd.
    assert targets[0].channel == "geopro"
    assert targets[0].target == "todd"
