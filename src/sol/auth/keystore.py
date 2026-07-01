# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""JWT signing key store with rotation support.

Layout of jwt_keys_dir (default /etc/sol/keys):
  current.key  current.pub        ← signing key (issue new tokens with this)
  prev-1.key   prev-1.pub          ← previous key (verify-only during grace)
  prev-2.key   prev-2.pub          ← older key (verify-only during grace)
  jwt_signing.key  jwt_signing.pub ← legacy single-key (backward compat)

SOL issues with current.{key,pub}. SOL verifies against any *.pub in the dir.

Token has a `kid` (key id) claim = the basename of the pub file (e.g. "current",
"prev-1"). Verifier looks up the pub by kid; if no kid, falls back to trying
every available pub (legacy tokens issued before rotation landed).

Each key file:
  *.key — PEM-encoded Ed25519 private key (also OK: HS256 hex secret in dev)
  *.pub — PEM-encoded Ed25519 public key

Rotation flow (operator):
  1. python scripts/rotate_jwt_key.py --new-name current --rotate-to prev-1
     → renames current.* to prev-1.* (overwriting any prev-1 there)
     → renames prev-1.* to prev-2.* first (keeps last 2)
     → generates fresh Ed25519 keypair as current.{key,pub}
     → fsync; chmod 600 key, 644 pub
  2. systemctl reload sol  (or restart — SIGHUP not yet wired)
  3. SOL begins issuing with new current; old tokens still verify against prev-1.
  4. After max(jwt_admin_ttl, jwt_service_ttl) elapsed, prev-2 can be deleted.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..settings import get_settings

LEGACY_KEY_BASENAME = "jwt_signing"


@dataclass(frozen=True)
class KeyMaterial:
    kid: str
    private_pem: str | None  # None for verify-only keys
    public_pem: str
    algorithm: str  # "EdDSA" for prod, "HS256" for dev fallback


_DEFAULT_DEV_SECRET = "dev-only-not-for-production-jwt-hmac-secret-32-chars-min!"


def _read(path: Path) -> str:
    with path.open() as f:
        return f.read()


def _discover(keys_dir: Path) -> dict[str, KeyMaterial]:
    """Return {kid: KeyMaterial} for every *.pub in keys_dir. The matching
    *.key (if present) is loaded as the private key."""
    out: dict[str, KeyMaterial] = {}
    if not keys_dir.is_dir():
        return out
    for pub in sorted(keys_dir.glob("*.pub")):
        kid = pub.stem  # e.g. "current", "prev-1", "jwt_signing"
        priv_path = keys_dir / f"{kid}.key"
        priv = _read(priv_path) if priv_path.is_file() else None
        out[kid] = KeyMaterial(
            kid=kid,
            private_pem=priv,
            public_pem=_read(pub),
            algorithm="EdDSA",
        )
    return out


@lru_cache(maxsize=1)
def _cached_keys() -> dict[str, KeyMaterial]:
    s = get_settings()
    return _discover(Path(s.jwt_keys_dir))


def reload_keys() -> None:
    """Drop the cache — used by tests + admin reload."""
    _cached_keys.cache_clear()


def all_verify_keys() -> dict[str, KeyMaterial]:
    """Every key SOL will accept for verification (current + prev + legacy)."""
    return _cached_keys()


def current_signing_key() -> KeyMaterial:
    """Key SOL uses to issue new tokens. Falls back per environment:
    1. <jwt_keys_dir>/current.{key,pub}                — preferred
    2. <jwt_signing_key_path> / <jwt_signing_pubkey_path>  — legacy single-key
    3. Dev HS256 secret                                — only when SOL_ENVIRONMENT != production
    """
    s = get_settings()
    keys = _cached_keys()

    current_name = s.jwt_current_key_name
    if current_name in keys and keys[current_name].private_pem:
        return keys[current_name]

    if LEGACY_KEY_BASENAME in keys and keys[LEGACY_KEY_BASENAME].private_pem:
        return keys[LEGACY_KEY_BASENAME]

    # Legacy explicit paths from settings (back-compat)
    leg_priv = Path(s.jwt_signing_key_path)
    leg_pub = Path(s.jwt_signing_pubkey_path)
    if leg_priv.is_file() and leg_pub.is_file():
        return KeyMaterial(
            kid=LEGACY_KEY_BASENAME,
            private_pem=_read(leg_priv),
            public_pem=_read(leg_pub),
            algorithm="EdDSA",
        )

    if s.environment == "production":
        raise RuntimeError(
            f"No signing key found in {s.jwt_keys_dir} or {s.jwt_signing_key_path}"
        )

    # Dev fallback — HS256 with static secret.
    return KeyMaterial(
        kid="dev",
        private_pem=_DEFAULT_DEV_SECRET,
        public_pem=_DEFAULT_DEV_SECRET,
        algorithm="HS256",
    )


def verify_key_for(kid: str | None) -> list[KeyMaterial]:
    """Return candidate verify keys.

    If kid is given and matches a known key, return just that one.
    If kid is unknown OR missing, return ALL keys so legacy tokens still verify.
    Always falls through to dev HS256 if no keys on disk in non-prod.
    """
    keys = _cached_keys()
    if kid and kid in keys:
        return [keys[kid]]

    s = get_settings()
    if keys:
        return list(keys.values())

    # No keys on disk at all
    leg_pub = Path(s.jwt_signing_pubkey_path)
    if leg_pub.is_file():
        return [
            KeyMaterial(
                kid=LEGACY_KEY_BASENAME,
                private_pem=None,
                public_pem=_read(leg_pub),
                algorithm="EdDSA",
            )
        ]

    if s.environment == "production":
        raise RuntimeError(f"No verify keys found in {s.jwt_keys_dir}")

    return [
        KeyMaterial(
            kid="dev",
            private_pem=None,
            public_pem=_DEFAULT_DEV_SECRET,
            algorithm="HS256",
        )
    ]


def ensure_keys_dir() -> None:
    """Create the keys dir if missing (used by rotate script)."""
    s = get_settings()
    p = Path(s.jwt_keys_dir)
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o750)
    except PermissionError:
        # Non-root caller — defer to ops
        pass
