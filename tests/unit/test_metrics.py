from fastapi.testclient import TestClient

from sol.main import create_app


def test_metrics_endpoint_exposes_prometheus():
    client = TestClient(create_app())
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "sol_dispatches_total" in body
    assert "sol_capabilities_active" in body
