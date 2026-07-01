# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Tests for the JWT key rotation keystore."""
from __future__ import annotations

from pathlib import Path

import jwt
import pytest

from sol.auth import keystore


def _write_ed25519_pair(dirp: Path, basename: str) -> tuple[str, str]:
    """Helper: generate an Ed25519 keypair and write basename.{key,pub}. Return PEMs."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    sk = ed25519.Ed25519PrivateKey.generate()
    pk = sk.public_key()
    key_pem = sk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = pk.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    (dirp / f"{basename}.key").write_text(key_pem)
    (dirp / f"{basename}.pub").write_text(pub_pem)
    return key_pem, pub_pem


@pytest.fixture
def keys_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOL_JWT_KEYS_DIR", str(tmp_path))
    monkeypatch.setenv("SOL_ENVIRONMENT", "production")
    from sol import settings as _s
    _s.get_settings.cache_clear()
    keystore.reload_keys()
    yield tmp_path
    keystore.reload_keys()


def test_current_key_loaded(keys_dir):
    _write_ed25519_pair(keys_dir, "current")
    keystore.reload_keys()
    km = keystore.current_signing_key()
    assert km.kid == "current"
    assert km.algorithm == "EdDSA"
    assert km.private_pem is not None


def test_prev_keys_accepted_for_verify(keys_dir):
    # Set up "current" + "prev-1"
    _write_ed25519_pair(keys_dir, "current")
    _write_ed25519_pair(keys_dir, "prev-1")
    keystore.reload_keys()

    keys = keystore.all_verify_keys()
    assert set(keys.keys()) == {"current", "prev-1"}


def test_token_signed_by_prev_still_verifies(keys_dir):
    # Issue with "current", then rotate so today's "current" becomes "prev-1"
    _write_ed25519_pair(keys_dir, "current")
    keystore.reload_keys()
    km_old = keystore.current_signing_key()
    token = jwt.encode(
        {"sub": "test", "iss": "sol"},
        km_old.private_pem,
        algorithm="EdDSA",
        headers={"kid": "current"},
    )

    # Simulate rotation: move current → prev-1, fresh current
    for ext in ("key", "pub"):
        (keys_dir / f"current.{ext}").rename(keys_dir / f"prev-1.{ext}")
    _write_ed25519_pair(keys_dir, "current")
    keystore.reload_keys()

    # The old token's kid is "current" but the file at "current" is the new
    # key; the verifier must try other keys when the kid-named one fails.
    # The admin/service verify loops do exactly this fall-through; we
    # simulate it here at the keystore layer to keep the test self-contained.
    decoded = None
    for km in keystore.all_verify_keys().values():
        try:
            decoded = jwt.decode(token, km.public_pem, algorithms=["EdDSA"], issuer="sol")
            break
        except jwt.PyJWTError:
            continue
    assert decoded is not None
    assert decoded["sub"] == "test"
