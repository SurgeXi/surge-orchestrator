"""Shared pytest fixtures."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch):
    """Force dev-mode signing material for unit tests."""
    monkeypatch.setenv("SOL_ENVIRONMENT", "dev")
    monkeypatch.setenv("SOL_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("SOL_JWT_SIGNING_KEY_PATH", "/nonexistent")
    monkeypatch.setenv("SOL_JWT_SIGNING_PUBKEY_PATH", "/nonexistent")
    monkeypatch.setenv("SOL_JWT_KEYS_DIR", "/nonexistent")
    monkeypatch.setenv("SOL_MTLS_CALLERS_YAML_PATH", "/nonexistent")
    # Allow mTLS tests to bypass loopback requirement
    monkeypatch.setenv("SOL_MTLS_REQUIRE_LOOPBACK", "false")
    # clear cached settings + keystore + mtls callers + revocation between tests
    from sol import settings as _s
    from sol.auth import keystore as _ks
    from sol.auth import mtls as _mtls
    from sol.auth import revocation as _rev
    _s.get_settings.cache_clear()
    _ks.reload_keys()
    _mtls.reload_callers()
    _rev.force_refresh()
    yield
    _s.get_settings.cache_clear()
    _ks.reload_keys()
    _mtls.reload_callers()
    _rev.force_refresh()
