"""Issue admin/service tokens. Writes to a 600 file; does NOT print secrets.

Usage:
  SOL_ENVIRONMENT=production \\
  SOL_JWT_SIGNING_KEY_PATH=/etc/sol/keys/jwt_signing.key \\
  SOL_JWT_SIGNING_PUBKEY_PATH=/etc/sol/keys/jwt_signing.pub \\
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
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--kind", choices=["admin", "service"], required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--role", default="admin")
    p.add_argument("--tenants", default="*")
    p.add_argument("--claims", nargs="*", default=[])
    p.add_argument("--out", required=True)
    args = p.parse_args()

    from sol.auth.jwt import AdminJwtAuth
    from sol.auth.service_tokens import ServiceTokenAuth

    allowed = [t.strip() for t in args.tenants.split(",") if t.strip()]
    if args.kind == "admin":
        token = AdminJwtAuth.issue(args.subject, args.role, allowed)
    else:
        token = ServiceTokenAuth.issue(args.subject, allowed, args.claims)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, token.encode("utf-8") + b"\n")
    finally:
        os.close(fd)
    os.chmod(out, 0o600)
    print(f"WROTE: {out} (mode 600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
