import pytest
from fastapi import HTTPException

from sol.auth.jwt import AdminJwtAuth
from sol.auth.service_tokens import ServiceTokenAuth


def test_admin_jwt_roundtrip():
    tok = AdminJwtAuth.issue("todd", "admin", ["*"])
    p = AdminJwtAuth.verify(tok)
    assert p.username == "todd"
    assert p.sol_role == "admin"
    assert p.allowed_tenants == ["*"]


def test_service_token_roundtrip():
    tok = ServiceTokenAuth.issue("brain", ["timesavedap", "surgexi"], ["dispatch"])
    p = ServiceTokenAuth.verify(tok)
    assert p.service_name == "brain"
    assert "timesavedap" in p.allowed_tenants


def test_service_token_rejected_as_admin():
    # Issuing does not grant admin verify.
    ServiceTokenAuth.issue("brain", ["*"])
    with pytest.raises(HTTPException):
        AdminJwtAuth.verify("garbage")
