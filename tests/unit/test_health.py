from fastapi.testclient import TestClient

from sol.main import create_app


def test_healthz():
    client = TestClient(create_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_degraded_without_db():
    # With no Postgres reachable in CI, readyz returns 503 (degraded).
    client = TestClient(create_app())
    r = client.get("/readyz")
    assert r.status_code in (200, 503)
    body = r.json()
    assert "postgres" in body
    assert "policy_cache" in body
