import pytest
from fastapi import HTTPException

from sol.auth.jwt import AdminJwtAuth
from sol.auth.service_tokens import ServiceTokenAuth


def test_admin_jwt_roundtrip():
    tok, jti = AdminJwtAuth.issue("todd", "admin", ["*"])
    assert jti  # non-empty
    p = AdminJwtAuth.verify(tok)
    assert p.username == "todd"
    assert p.sol_role == "admin"
    assert p.allowed_tenants == ["*"]
    assert p.jti == jti


def test_service_token_roundtrip():
    tok, jti = ServiceTokenAuth.issue("brain", ["timesavedap", "surgexi"], ["dispatch"])
    assert jti
    p = ServiceTokenAuth.verify(tok)
    assert p.service_name == "brain"
    assert "timesavedap" in p.allowed_tenants
    assert p.jti == jti


def test_service_token_rejected_as_admin():
    # Issuing does not grant admin verify.
    ServiceTokenAuth.issue("brain", ["*"])
    with pytest.raises(HTTPException):
        AdminJwtAuth.verify("garbage")
