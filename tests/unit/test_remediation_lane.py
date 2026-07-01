# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Lane-decision tests: prove the auto-remediation FLIP only happens when the
flag is ON *and* the request matches a curated playbook. Mirrors the exact
condition in sol.api.dispatch (``needs_human and s.auto_remediation and
classify_remediation(args) is not None``) without needing a live Postgres.
"""
from __future__ import annotations

from sol.policy.remediation import classify_remediation
from sol.settings import Settings

SCRIPT = "/usr/local/bin/surge-qdrant-snapshot-retention.sh"


def _flip_to_auto(needs_human: bool, auto_remediation: bool, args: dict) -> tuple[bool, str | None]:
    """The exact dispatch lane decision, replicated for unit isolation."""
    remediation_name = None
    if needs_human and auto_remediation:
        remediation_name = classify_remediation(args)
        if remediation_name is not None:
            needs_human = False
    return needs_human, remediation_name


def _retention(apply: bool = True) -> dict:
    cmd = SCRIPT + (" --apply" if apply else "")
    return {"tool": "run_bash", "args": {"cmd": cmd}}


# ---- flag default ----

def test_auto_remediation_defaults_off():
    assert Settings(_env_file=None).auto_remediation is False


# ---- SAFE FIRES: flag on + curated match => auto-approved ----

def test_flag_on_curated_match_flips_to_auto():
    needs_human, name = _flip_to_auto(True, True, _retention(apply=True))
    assert needs_human is False
    assert name == "disk-pressure-qdrant-retention"


# ---- ESCALATES: flag OFF, even on a perfect match, stays human-gated ----

def test_flag_off_perfect_match_still_gated():
    needs_human, name = _flip_to_auto(True, False, _retention(apply=True))
    assert needs_human is True
    assert name is None


# ---- ESCALATES: flag on but request not curated => stays human-gated ----

def test_flag_on_non_curated_stays_gated():
    bad = {"tool": "run_bash", "args": {"cmd": "rm -rf /srv/backups/surge"}}
    needs_human, name = _flip_to_auto(True, True, bad)
    assert needs_human is True
    assert name is None


def test_flag_on_keep1_stays_gated():
    bad = {"tool": "run_bash", "args": {"cmd": f"KEEP=1 {SCRIPT} --apply"}}
    needs_human, name = _flip_to_auto(True, True, bad)
    assert needs_human is True
    assert name is None


# ---- a request that never needed a human is untouched by the lane ----

def test_already_auto_not_affected():
    needs_human, name = _flip_to_auto(False, True, _retention())
    assert needs_human is False
    # name is None because the lane only classifies when needs_human was True
    assert name is None
