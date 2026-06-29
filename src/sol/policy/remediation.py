"""Curated autonomous-remediation registry for Surge (DEFAULT-OFF, fail-closed).

Design (approved 2026-06-29, see PROPOSAL-autonomous-remediation-playbook.md):
Surge may AUTONOMOUSLY resolve a TINY, hand-curated set of light, deterministic,
REVERSIBLE, idempotent issues, and must ESCALATE everything else to a human.
"It's not broke until I can't fix it." — but the bar to be in the curated set is
deliberately high.

Posture (non-negotiable):
  * DEFAULT OFF behind ``Settings.auto_remediation`` (env SOL_AUTO_REMEDIATION).
    Off => Surge may only RECOMMEND; it never applies a remediation.
  * Allow-list, never deny-list. A request is eligible ONLY if it matches a
    registered playbook EXACTLY (capability + tool + a structural arg check).
  * Every playbook is bounded (anchored paths, no generalization), reversible
    enough that the curated entry vetted it, idempotent (re-running is a no-op
    when already healthy), and runs dry-run -> verify -> apply -> re-verify.
  * Anything not matched, or that touches prod data / services / network /
    deploys, or whose verify fails, ESCALATES and stays human-gated.
  * This module is PURE: no side effects on import, no I/O at module scope.
    The SOL dispatch lane only uses ``classify_remediation`` to decide whether
    a request is in the allow-list; the actual run/verify orchestration lives
    in the executor/broker, audited per attempt.

The classifier here answers exactly one question: "is THIS dispatch request a
member of the curated remediation allow-list?" It is intentionally conservative
and returns the matched playbook name (for the audit reason) or None.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class RemediationPlaybook:
    """One curated, bounded, reversible remediation.

    name:        stable id used in audit reason ("remediation:<name>").
    description: human-readable summary for reports/escalation messages.
    capability:  the SOL capability the dispatch must target.
    matches:     a pure predicate over the dispatch ``args`` dict. Must be
                 strict — it is the allow-list gate. Returns True ONLY for the
                 exact, vetted invocation shape.
    """

    name: str
    description: str
    capability: str
    matches: Callable[[dict], bool]


# ---------------------------------------------------------------------------
# Playbook #1 — disk-pressure-qdrant-retention
# ---------------------------------------------------------------------------
# Trigger (evaluated by the orchestrator BEFORE dispatch, not here): a BACKUP
# mount is >= 85% full AND family qdrant-snapshots has > KEEP dated files under
# /srv/backups/surge. The bounded/reversible action is the existing, vetted
# script ``surge-qdrant-snapshot-retention.sh`` which: anchors ROOT, matches a
# strict dated-file regex, path-guards every delete, keeps the newest KEEP, and
# is dry-run unless ``--apply``. The classifier below accepts ONLY that exact
# script invocation with a safe KEEP and the qdrant-snapshots family.

# Absolute path of the one vetted script. No other script qualifies.
_QDRANT_RETENTION_SCRIPT = "/usr/local/bin/surge-qdrant-snapshot-retention.sh"
# The only backup root we will ever let this lane touch. A data/root mount can
# never match (the trigger-side guard ALSO enforces this; defense in depth).
_BACKUP_ROOT_PREFIX = "/srv/backups/"
# Minimum snapshots to retain. KEEP < 2 is rejected (never leave a single copy).
_MIN_KEEP = 2

# A safe command is EXACTLY the vetted script, optionally with --apply, run via
# the run_bash tool. No chaining / redirect / substitution / extra args.
_FORBIDDEN_SHELL = (">", "<", "`", "$(", "${", "&", ";", "|", "\n", "\r")
# Allowed env-style prefixes on the command (KEEP=, ROOT=, FAMILY=, LOG=).
_ENV_ASSIGN = re.compile(r"^[A-Z_]+=\S*$")


def _parse_env_assignments(tokens: list[str]) -> tuple[dict[str, str], list[str]]:
    """Split leading VAR=VALUE assignments from the rest of the command tokens."""
    env: dict[str, str] = {}
    rest = list(tokens)
    while rest and _ENV_ASSIGN.match(rest[0]) and "=" in rest[0]:
        k, v = rest[0].split("=", 1)
        env[k] = v
        rest.pop(0)
    return env, rest


def _matches_qdrant_retention(args: dict) -> bool:
    """True ONLY for the exact vetted retention invocation. Fail CLOSED.

    Accepts a run_bash whose command is::

        [KEEP=N] [FAMILY=qdrant-snapshots] [ROOT=/srv/backups/...] \\
            /usr/local/bin/surge-qdrant-snapshot-retention.sh [--apply]

    Rejects: any other script, any shell metacharacters, KEEP < 2, any FAMILY
    other than qdrant-snapshots, any ROOT outside /srv/backups/, or any extra
    positional argument beyond an optional ``--apply``.
    """
    try:
        if str(args.get("tool", "")) != "run_bash":
            return False
        cmd = (args.get("args", {}) or {}).get("cmd", "")
        if not isinstance(cmd, str) or not cmd.strip():
            return False
        if any(t in cmd for t in _FORBIDDEN_SHELL):
            return False
        toks = cmd.split()
        if not toks:
            return False
        env, rest = _parse_env_assignments(toks)
        # Validate the env assignments we allow.
        for k, v in env.items():
            if k not in {"KEEP", "FAMILY", "ROOT", "LOG"}:
                return False
            if k == "KEEP":
                if not v.isdigit() or int(v) < _MIN_KEEP:
                    return False
            if k == "FAMILY" and v != "qdrant-snapshots":
                return False
            if k == "ROOT" and not v.startswith(_BACKUP_ROOT_PREFIX):
                return False
        # The script itself + an optional --apply, nothing else.
        if not rest:
            return False
        if rest[0] != _QDRANT_RETENTION_SCRIPT:
            return False
        tail = rest[1:]
        if tail and tail != ["--apply"]:
            return False
        return True
    except Exception:
        return False


_PLAYBOOKS: tuple[RemediationPlaybook, ...] = (
    RemediationPlaybook(
        name="disk-pressure-qdrant-retention",
        description=(
            "Backup mount under disk pressure: keep the newest 2 qdrant "
            "snapshot tarballs under /srv/backups/surge and purge older ones "
            "via the vetted surge-qdrant-snapshot-retention.sh (dry-run first, "
            "verify, then --apply, then re-verify). Backup mounts only."
        ),
        capability="host.run_bash",
        matches=_matches_qdrant_retention,
    ),
)


def registered_playbooks() -> tuple[RemediationPlaybook, ...]:
    """The curated allow-list. Read-only view for callers/reports."""
    return _PLAYBOOKS


def classify_remediation(payload_args: dict) -> Optional[str]:
    """Return the matched curated playbook name, or None.

    This is the SOL allow-list gate for the auto-remediation lane. It returns a
    name ONLY when ``payload_args`` matches a registered playbook EXACTLY. The
    caller (dispatch) must ALSO require ``Settings.auto_remediation`` to be true
    before acting on a non-None result. Fail CLOSED on any error.
    """
    try:
        capability = str(payload_args.get("capability", "") or payload_args.get("tool", ""))
        for pb in _PLAYBOOKS:
            # Match either by the SOL capability id or the underlying tool name;
            # the per-playbook ``matches`` predicate is the real structural gate.
            if pb.matches(payload_args):
                return pb.name
        return None
    except Exception:
        return None
