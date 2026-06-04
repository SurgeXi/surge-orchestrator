"""mTLS verifier (Phase 3 hardening — code in place, wiring in Week 1 follow-up)."""
from __future__ import annotations

import ssl
from dataclasses import dataclass


@dataclass
class MtlsPrincipal:
    subject_cn: str
    issuer_cn: str


def build_server_ssl_context(cert: str, key: str, ca: str) -> ssl.SSLContext:
    """Build an mTLS-requiring SSLContext.

    Caller passes paths; for Phase 3.1 this is wired by uvicorn-side --ssl-* flags
    on a sidecar port. Full integration when SOL_MTLS_ENABLED=true.
    """
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.load_verify_locations(cafile=ca)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    return ctx
