# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Issue admin/service tokens. Writes to a 600 file; does NOT print secrets.

Persists issuance metadata to sol.issued_tokens when reachable (so revoke
works against tokens issued via this CLI).

Usage:
  SOL_ENVIRONMENT=production \\
  SOL_JWT_KEYS_DIR=/etc/sol/keys \\
  PYTHONPATH=src python scripts/issue_tokens.py \\
      --kind admin --subject todd --role admin --out /etc/sol/tokens/todd-admin.jwt

  SOL_ENVIRONMENT=production ... PYTHONPATH=src python scripts/issue_tokens.py \\
      --kind service --subject brain --tenants '*' \\
      --claims dispatch register_capability \\
      --out /etc/sol/tokens/brain.service-token

The output file is created with mode 600 (octal). Existing files are overwritten.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--kind", choices=["admin", "service"], required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--role", default="admin")
    p.add_argument("--tenants", default="*")
    p.add_argument("--claims", nargs="*", default=[])
    p.add_argument("--out", required=True)
    p.add_argument(
        "--skip-db",
        action="store_true",
        help="Do not persist issuance to sol.issued_tokens (use when DB unreachable).",
    )
    args = p.parse_args()

    from sol.auth.jwt import AdminJwtAuth
    from sol.auth.keystore import current_signing_key
    from sol.auth.service_tokens import ServiceTokenAuth
    from sol.settings import get_settings

    s = get_settings()
    allowed = [t.strip() for t in args.tenants.split(",") if t.strip()]
    km = current_signing_key()

    if args.kind == "admin":
        token, jti = AdminJwtAuth.issue(args.subject, args.role, allowed)
        expires_at = datetime.now(UTC) + timedelta(minutes=s.jwt_admin_ttl_minutes)
        capabilities = [args.role]
    else:
        token, jti = ServiceTokenAuth.issue(args.subject, allowed, args.claims)
        expires_at = datetime.now(UTC) + timedelta(days=s.jwt_service_ttl_days)
        capabilities = args.claims

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, token.encode("utf-8") + b"\n")
    finally:
        os.close(fd)
    os.chmod(out, 0o600)

    if not args.skip_db:
        try:
            from sol.db import get_session_factory
            from sol.models import IssuedToken

            with get_session_factory()() as session:
                session.add(
                    IssuedToken(
                        jti=jti,
                        issued_by=f"cli:{os.getenv('USER', 'unknown')}",
                        kind=args.kind,
                        audience=args.subject,
                        capabilities=list(capabilities),
                        expires_at=expires_at,
                        kid=km.kid,
                    )
                )
                session.commit()
            print(f"WROTE: {out} (mode 600); jti={jti} kid={km.kid} persisted")
        except Exception as e:
            print(f"WROTE: {out} (mode 600); jti={jti} kid={km.kid}", file=sys.stderr)
            print(f"WARNING: failed to persist to sol.issued_tokens: {e}", file=sys.stderr)
            print("  Run with --skip-db to suppress this warning.", file=sys.stderr)
    else:
        print(f"WROTE: {out} (mode 600); jti={jti} kid={km.kid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
