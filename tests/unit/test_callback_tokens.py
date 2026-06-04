"""Unit tests for the signed one-tap callback token signer."""
from __future__ import annotations

import time
import uuid

import pytest
from fastapi import HTTPException

from sol.auth import callback_tokens


@pytest.fixture(autouse=True)
def _clear_secret_cache():
    callback_tokens.reset_secret_cache()
    yield
    callback_tokens.reset_secret_cache()


def test_roundtrip_approve():
    aid = uuid.uuid4()
    token = callback_tokens.issue(aid, "approve")
    claims = callback_tokens.verify(token)
    assert claims.approval_id == aid
    assert claims.decision == "approve"
    assert claims.exp_unix > int(time.time())


def test_roundtrip_deny():
    aid = uuid.uuid4()
    token = callback_tokens.issue(aid, "deny")
    claims = callback_tokens.verify(token)
    assert claims.decision == "deny"


def test_rejects_invalid_decision():
    with pytest.raises(ValueError):
        callback_tokens.issue(uuid.uuid4(), "maybe")


def test_rejects_tampered_signature():
    token = callback_tokens.issue(uuid.uuid4(), "approve")
    # Flip last char of the sig
    bad = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(HTTPException) as exc:
        callback_tokens.verify(bad)
    assert exc.value.status_code == 401


def test_rejects_swapped_decision():
    """An approve URL must not verify if the decision claim is rewritten."""
    aid = uuid.uuid4()
    token = callback_tokens.issue(aid, "approve")
    # Caller swaps "approve" → "deny" in the URL body; that breaks the HMAC.
    body_id, body_dec, body_exp, body_sig = token.split(".", 3)
    swapped = f"{body_id}.deny.{body_exp}.{body_sig}"
    with pytest.raises(HTTPException) as exc:
        callback_tokens.verify(swapped)
    assert exc.value.status_code == 401


def test_rejects_expired_token():
    aid = uuid.uuid4()
    token = callback_tokens.issue(aid, "approve", ttl_minutes=0)
    # Wait one full second to ensure exp < now.
    time.sleep(1.1)
    with pytest.raises(HTTPException) as exc:
        callback_tokens.verify(token)
    assert exc.value.detail == "callback_token_expired"


def test_rejects_malformed_token():
    with pytest.raises(HTTPException):
        callback_tokens.verify("not-a-token")
