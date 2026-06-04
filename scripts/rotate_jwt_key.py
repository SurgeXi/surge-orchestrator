"""Rotate the SOL JWT signing key.

Layout invariant after rotation:
  current.{key,pub}   ← fresh Ed25519 keypair (SOL signs new tokens with this)
  prev-1.{key,pub}    ← previous current (verify-only during grace)
  prev-2.{key,pub}    ← previous prev-1 (verify-only; deleted after grace)

Existing prev-2 is removed before rotation (we keep last 2 verify keys).

Usage (must run as a user with write access to /etc/sol/keys):

  sudo -E python scripts/rotate_jwt_key.py \\
      --keys-dir /etc/sol/keys

After rotation, restart SOL so workers pick up the new current key:
  sudo systemctl restart sol

Safety:
  - Aborts if /etc/sol/keys is not writable (no half-rotation).
  - Generates the new keypair in a temp dir then renames into place atomically.
  - Prints jti / kid status only — never prints the private key.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _generate_ed25519_pair(out_key: Path, out_pub: Path) -> None:
    """Generate Ed25519 keypair via the cryptography library and write PEM."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    sk = ed25519.Ed25519PrivateKey.generate()
    pk = sk.public_key()

    key_pem = sk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = pk.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    out_key.write_bytes(key_pem)
    out_pub.write_bytes(pub_pem)
    os.chmod(out_key, 0o600)
    os.chmod(out_pub, 0o644)


def _move_pair(keys_dir: Path, src_base: str, dst_base: str) -> bool:
    """Move <src_base>.{key,pub} → <dst_base>.{key,pub}. Returns False if src absent."""
    src_key = keys_dir / f"{src_base}.key"
    src_pub = keys_dir / f"{src_base}.pub"
    if not src_key.exists() and not src_pub.exists():
        return False
    dst_key = keys_dir / f"{dst_base}.key"
    dst_pub = keys_dir / f"{dst_base}.pub"
    # Remove anything currently sitting at dst.
    for p in (dst_key, dst_pub):
        if p.exists():
            p.unlink()
    if src_key.exists():
        src_key.rename(dst_key)
    if src_pub.exists():
        src_pub.rename(dst_pub)
    return True


def main() -> int:
    p = argparse.ArgumentParser(description="Rotate SOL JWT signing key.")
    p.add_argument(
        "--keys-dir",
        default="/etc/sol/keys",
        help="Directory holding the keypairs (default: /etc/sol/keys).",
    )
    p.add_argument(
        "--keep-prev",
        type=int,
        default=2,
        help="How many prev-N keys to retain for verification grace.",
    )
    args = p.parse_args()

    keys_dir = Path(args.keys_dir)
    if not keys_dir.is_dir():
        print(f"ERROR: {keys_dir} does not exist or is not a directory.", file=sys.stderr)
        return 2
    if not os.access(keys_dir, os.W_OK):
        print(f"ERROR: {keys_dir} is not writable by current user.", file=sys.stderr)
        return 2

    # Drop oldest prev (prev-N where N == keep_prev) — it'll be replaced by the cascade.
    oldest = f"prev-{args.keep_prev}"
    for ext in ("key", "pub"):
        p_old = keys_dir / f"{oldest}.{ext}"
        if p_old.exists():
            p_old.unlink()
            print(f"  removed {p_old}")

    # Cascade prev-(N-1) → prev-N, prev-(N-2) → prev-(N-1), ... prev-1 → prev-2
    for i in range(args.keep_prev - 1, 0, -1):
        src = f"prev-{i}"
        dst = f"prev-{i + 1}"
        if _move_pair(keys_dir, src, dst):
            print(f"  moved {src}.* → {dst}.*")

    # Move current → prev-1
    if _move_pair(keys_dir, "current", "prev-1"):
        print("  moved current.* → prev-1.*")

    # Generate fresh current in a tmpdir, then move atomically
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        new_key = tmp / "current.key"
        new_pub = tmp / "current.pub"
        _generate_ed25519_pair(new_key, new_pub)
        # Move into keys_dir
        shutil.move(str(new_key), str(keys_dir / "current.key"))
        shutil.move(str(new_pub), str(keys_dir / "current.pub"))
        os.chmod(keys_dir / "current.key", 0o600)
        os.chmod(keys_dir / "current.pub", 0o644)
    print("  wrote fresh current.{key,pub}")

    # Print the new current public key fingerprint (sha256) for ops record.
    import hashlib

    fp = hashlib.sha256((keys_dir / "current.pub").read_bytes()).hexdigest()
    print(f"  current.pub sha256: {fp}")
    print()
    print("ROTATION COMPLETE.")
    print("Next steps:")
    print("  1. sudo systemctl restart sol      # workers pick up new current")
    print("  2. verify with: python scripts/issue_tokens.py --kind admin ...")
    print("  3. previous tokens (signed by prev-1) continue to verify until expiry")
    return 0


if __name__ == "__main__":
    sys.exit(main())
