from sol.settings import get_settings


def test_defaults_load(monkeypatch):
    monkeypatch.setenv("SOL_ENFORCE", "false")
    monkeypatch.setenv("SOL_SHADOW_ENABLED", "true")
    from sol import settings as _s

    _s.get_settings.cache_clear()
    s = get_settings()
    assert s.port == 9320
    assert s.is_shadow_only is True
    assert s.jwt_admin_ttl_minutes == 60
    assert s.jwt_service_ttl_days == 90


def test_policy_expiry_defaults():
    from sol.policy.cache import PolicyCache

    c = PolicyCache()
    c.load_from_yaml("/nonexistent/path/policy.yaml")
    assert c.is_loaded
    assert c.expiry_for("anything", "money") == 4 * 3600
    assert c.expiry_for("anything", "tenant") == 8 * 3600
    assert c.expiry_for("anything", "standard") == 24 * 3600
    assert c.expiry_for("anything", "onboarding") == 72 * 3600
    assert c.expiry_for("anything", "read_only") == 1 * 3600
    assert c.expiry_for("anything") == 24 * 3600
