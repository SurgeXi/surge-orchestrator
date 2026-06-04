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
    # clear cached settings between tests so env changes apply
    from sol import settings as _s
    _s.get_settings.cache_clear()
    yield
    _s.get_settings.cache_clear()
