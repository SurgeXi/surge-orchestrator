# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Tests for the mTLS auth path (header-based, after nginx termination)."""
from __future__ import annotations

import pytest
import yaml
from fastapi import HTTPException
from starlette.requests import Request

from sol.auth.mtls import extract_mtls_principal, reload_callers


def _make_request(headers: dict[str, str], client_host: str = "127.0.0.1") -> Request:
    """Build a Starlette Request with the given headers + client host."""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": (client_host, 12345),
    }
    return Request(scope)


def test_no_headers_returns_none():
    req = _make_request({})
    assert extract_mtls_principal(req) is None


def test_verified_with_known_caller(tmp_path, monkeypatch):
    callers = tmp_path / "callers.yaml"
    callers.write_text(
        yaml.safe_dump(
            {
                "callers": {
                    "brain": {
                        "allowed_tenants": ["*"],
                        "claims": ["dispatch", "register_capability"],
                    }
                }
            }
        )
    )
    monkeypatch.setenv("SOL_MTLS_CALLERS_YAML_PATH", str(callers))
    from sol import settings as _s
    _s.get_settings.cache_clear()
    reload_callers()

    req = _make_request(
        {
            "X-Client-Cert-Verified": "SUCCESS",
            "X-Client-CN": "brain.sol-client",
        }
    )
    p = extract_mtls_principal(req)
    assert p is not None
    assert p.client_cn == "brain.sol-client"
    assert p.caller_name == "brain"
    assert p.allowed_tenants == ["*"]
    assert "dispatch" in p.claims


def test_failed_verify_rejected(tmp_path, monkeypatch):
    callers = tmp_path / "callers.yaml"
    callers.write_text(yaml.safe_dump({"callers": {"brain": {"allowed_tenants": ["*"]}}}))
    monkeypatch.setenv("SOL_MTLS_CALLERS_YAML_PATH", str(callers))
    from sol import settings as _s
    _s.get_settings.cache_clear()
    reload_callers()

    req = _make_request(
        {
            "X-Client-Cert-Verified": "FAILED:expired",
            "X-Client-CN": "brain.sol-client",
        }
    )
    with pytest.raises(HTTPException) as ei:
        extract_mtls_principal(req)
    assert ei.value.status_code == 401


def test_unknown_caller_rejected(tmp_path, monkeypatch):
    callers = tmp_path / "callers.yaml"
    callers.write_text(yaml.safe_dump({"callers": {"brain": {"allowed_tenants": ["*"]}}}))
    monkeypatch.setenv("SOL_MTLS_CALLERS_YAML_PATH", str(callers))
    from sol import settings as _s
    _s.get_settings.cache_clear()
    reload_callers()

    req = _make_request(
        {
            "X-Client-Cert-Verified": "SUCCESS",
            "X-Client-CN": "evil.sol-client",
        }
    )
    with pytest.raises(HTTPException) as ei:
        extract_mtls_principal(req)
    assert ei.value.status_code == 403


def test_bad_cn_format_rejected(monkeypatch):
    req = _make_request(
        {
            "X-Client-Cert-Verified": "SUCCESS",
            "X-Client-CN": "no-suffix",
        }
    )
    with pytest.raises(HTTPException) as ei:
        extract_mtls_principal(req)
    assert ei.value.status_code == 401


def test_nginx_shared_secret_required(tmp_path, monkeypatch):
    """When nginx_shared_secret file exists, requests must echo it."""
    callers = tmp_path / "callers.yaml"
    callers.write_text(yaml.safe_dump({"callers": {"brain": {"allowed_tenants": ["*"]}}}))
    secret_file = tmp_path / "nginx-secret"
    secret_file.write_text("super-secret-token\n")
    monkeypatch.setenv("SOL_MTLS_CALLERS_YAML_PATH", str(callers))
    monkeypatch.setenv("SOL_NGINX_SHARED_SECRET_PATH", str(secret_file))
    from sol import settings as _s
    _s.get_settings.cache_clear()
    reload_callers()

    # Missing secret token => 401
    req = _make_request(
        {
            "X-Client-Cert-Verified": "SUCCESS",
            "X-Client-CN": "brain.sol-client",
        }
    )
    with pytest.raises(HTTPException) as ei:
        extract_mtls_principal(req)
    assert ei.value.status_code == 401
    assert "nginx-token mismatch" in ei.value.detail

    # Wrong secret token => 401
    req = _make_request(
        {
            "X-Client-Cert-Verified": "SUCCESS",
            "X-Client-CN": "brain.sol-client",
            "X-SOL-Nginx-Token": "wrong",
        }
    )
    with pytest.raises(HTTPException) as ei:
        extract_mtls_principal(req)
    assert ei.value.status_code == 401

    # Correct secret token => allowed
    req = _make_request(
        {
            "X-Client-Cert-Verified": "SUCCESS",
            "X-Client-CN": "brain.sol-client",
            "X-SOL-Nginx-Token": "super-secret-token",
        }
    )
    p = extract_mtls_principal(req)
    assert p is not None
    assert p.caller_name == "brain"


def test_loopback_required_rejects_non_loopback(tmp_path, monkeypatch):
    callers = tmp_path / "callers.yaml"
    callers.write_text(yaml.safe_dump({"callers": {"brain": {"allowed_tenants": ["*"]}}}))
    monkeypatch.setenv("SOL_MTLS_CALLERS_YAML_PATH", str(callers))
    monkeypatch.setenv("SOL_MTLS_REQUIRE_LOOPBACK", "true")
    from sol import settings as _s
    _s.get_settings.cache_clear()
    reload_callers()

    req = _make_request(
        {
            "X-Client-Cert-Verified": "SUCCESS",
            "X-Client-CN": "brain.sol-client",
        },
        client_host="10.0.0.5",
    )
    with pytest.raises(HTTPException) as ei:
        extract_mtls_principal(req)
    assert ei.value.status_code == 401
