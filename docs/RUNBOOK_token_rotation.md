# SOL Token Rotation Runbook

This runbook covers the two ongoing token-hygiene operations SOL operators
perform:

1. **JWT signing key rotation** — replace the active signing keypair while
   keeping old tokens verifiable during a grace window.
2. **Per-token revocation** — invalidate a specific JWT (admin or service)
   before its natural expiry.

The infrastructure was delivered in Phase 3.2 (mTLS + token rotation PR).

---

## 1. JWT signing key rotation

### When to rotate

| Trigger | Action |
| --- | --- |
| Quarterly scheduled rotation | rotate; keep prev-1 for one grace window |
| Suspected key compromise | rotate + revoke all in-flight tokens (see §3 below) |
| Personnel change with key access | rotate within 24h |
| After a planned algorithm change (e.g. RSA → Ed25519) | rotate; bump `kid` naming convention |

Service tokens have a 90-day TTL. Admin JWTs have a 60-minute TTL. The maximum
grace window required after rotation = 90 days (the longest in-flight token's
TTL). `prev-1` MUST be retained at least that long; `prev-2` after that is
optional but recommended for forensics.

### Layout

`/etc/sol/keys/` contains:

```
current.key  current.pub          ← SOL signs new tokens with this
prev-1.key   prev-1.pub           ← previously current; still verifies
prev-2.key   prev-2.pub           ← older prev; verify-only, optional
```

Both `.key` files are mode `600`, root-owned. Both `.pub` files are mode
`644`. SOL reads them on startup; rotation requires `systemctl restart sol`
to take effect (no SIGHUP yet).

### Rotation procedure

Run on **surgecore** as a user with write access to `/etc/sol/keys/`:

```bash
sudo -E /opt/sol/venv/bin/python /opt/sol/scripts/rotate_jwt_key.py \
    --keys-dir /etc/sol/keys
```

Expected output:

```
  removed /etc/sol/keys/prev-2.key
  removed /etc/sol/keys/prev-2.pub
  moved prev-1.* → prev-2.*
  moved current.* → prev-1.*
  wrote fresh current.{key,pub}
  current.pub sha256: <fingerprint>

ROTATION COMPLETE.
Next steps:
  1. sudo systemctl restart sol      # workers pick up new current
  2. verify with: python scripts/issue_tokens.py --kind admin ...
  3. previous tokens (signed by prev-1) continue to verify until expiry
```

Restart SOL workers:

```bash
sudo systemctl restart sol
```

### Verification

Confirm new signing key is active by issuing a fresh admin token and decoding
its `kid` header:

```bash
# 1. Issue a test admin token (writes to /etc/sol/tokens/test.jwt mode 600)
sudo -E SOL_ENVIRONMENT=production \
    PYTHONPATH=/opt/sol/src \
    /opt/sol/venv/bin/python /opt/sol/scripts/issue_tokens.py \
    --kind admin --subject test --role viewer \
    --out /tmp/test.jwt

# 2. Decode the header — kid should be "current"
sudo cat /tmp/test.jwt | cut -d. -f1 | base64 -d 2>/dev/null
# Expect: {"typ":"JWT","alg":"EdDSA","kid":"current"}

# 3. Verify SOL accepts it
curl -sS -H "Authorization: Bearer $(sudo cat /tmp/test.jwt)" \
    http://127.0.0.1:9320/v1/sol/audit?limit=1 | head -c 200
```

A pre-rotation token (signed by prev-1) must still verify until its `exp`:

```bash
curl -sS -H "Authorization: Bearer <pre-rotation-token>" \
    http://127.0.0.1:9320/v1/sol/audit?limit=1 | head -c 200
```

### Rollback

If the new key is bad or SOL won't start:

```bash
sudo systemctl stop sol
sudo mv /etc/sol/keys/current.key /etc/sol/keys/bad.key
sudo mv /etc/sol/keys/current.pub /etc/sol/keys/bad.pub
sudo mv /etc/sol/keys/prev-1.key  /etc/sol/keys/current.key
sudo mv /etc/sol/keys/prev-1.pub  /etc/sol/keys/current.pub
sudo systemctl start sol
```

(Newly issued tokens after rotation will be invalid — they were signed by
the discarded `bad.key`. Those holders re-issue via `issue_tokens.py`.)

---

## 2. Per-token revocation

### When to revoke

| Trigger | Action |
| --- | --- |
| Service compromise | revoke immediately; reissue |
| Departing operator | revoke admin JWT |
| Audit finding | revoke + audit forensics |
| Token leaked in chat / logs | revoke immediately |

Revocation is **per-jti** — each token has a unique JWT ID at issue time.
Revocation is persistent (`sol.revoked_tokens` row) and propagates to other
SOL workers within `SOL_REVOKED_TOKEN_CACHE_TTL_SECONDS` (default 300s).

### Revocation procedure

You need an **admin JWT** (`sol_role=admin`) to revoke. From any host with
network access to SOL on `127.0.0.1:9320` (or via the mTLS port `9321` with
`sol-admin` client cert):

```bash
ADMIN_TOKEN=$(sudo cat /etc/sol/tokens/todd-admin.jwt)
TARGET_JTI=<jti-to-revoke>

curl -sS -X POST \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"reason": "<why>"}' \
    http://127.0.0.1:9320/v1/sol/tokens/${TARGET_JTI}/revoke
```

Expected response:

```json
{
  "jti": "<jti>",
  "revoked_at": "2026-...",
  "already_revoked": false
}
```

### Finding the jti to revoke

List recent issued tokens by audience or by issued_by:

```bash
curl -sS -H "Authorization: Bearer $ADMIN_TOKEN" \
    "http://127.0.0.1:9320/v1/sol/tokens/issued?audience=brain&limit=20"
```

Or query Postgres directly:

```bash
psql "$SOL_DATABASE_URL" -c \
    "SELECT jti, kind, audience, issued_by, issued_at FROM sol.issued_tokens
       WHERE audience='brain' ORDER BY issued_at DESC LIMIT 10;"
```

### Verification that revocation took effect

```bash
# Should now return 401 token revoked
curl -i -H "X-SOL-Service-Token: <revoked-token>" \
    http://127.0.0.1:9320/v1/sol/audit?limit=1
```

Other SOL workers honor the revocation after the in-memory cache TTL
(default 300s). To force-propagate immediately, restart SOL workers:

```bash
sudo systemctl restart sol
```

### Rollback

A revocation is **not reversible** — once a jti is in `sol.revoked_tokens`,
SOL rejects any token with that jti permanently. The fix is to **re-issue**
a new token for the same audience:

```bash
sudo -E SOL_ENVIRONMENT=production PYTHONPATH=/opt/sol/src \
    /opt/sol/venv/bin/python /opt/sol/scripts/issue_tokens.py \
    --kind service --subject brain --tenants '*' \
    --claims dispatch register_capability \
    --out /etc/brain/sol-mtls/brain.service-token
```

If the revocation was a mistake and you absolutely must un-revoke (e.g. test
data accidentally entered prod), do it via SQL — and audit it:

```bash
psql "$SOL_DATABASE_URL" -c \
    "DELETE FROM sol.revoked_tokens WHERE jti='<jti>';"
sudo systemctl restart sol  # force cache reload
```

---

## 3. Combined "key compromise" response

If the active signing key is suspected leaked:

```bash
# 1. Rotate immediately
sudo -E /opt/sol/venv/bin/python /opt/sol/scripts/rotate_jwt_key.py
sudo systemctl restart sol

# 2. Revoke EVERY in-flight token from the previous key
psql "$SOL_DATABASE_URL" <<'SQL'
INSERT INTO sol.revoked_tokens (jti, revoked_by, reason)
SELECT jti, 'incident-response', 'key compromise: prev-1 invalidated'
FROM sol.issued_tokens
WHERE kid='prev-1' AND expires_at > now()
ON CONFLICT (jti) DO NOTHING;
SQL

# 3. Restart SOL again to flush revocation cache.
sudo systemctl restart sol

# 4. Re-issue all callers.
```

Document the incident in `docs/INCIDENTS/<date>-jwt-key-compromise.md` per
the SurgeXi incident playbook.

---

## 4. References

- Spec: `project_sol_buildable_spec.md` §4 (auth + identity model)
- Code: `src/sol/auth/keystore.py`, `src/sol/auth/revocation.py`, `src/sol/api/tokens.py`
- Schema: `alembic/versions/0006_sol_token_audit.py`
- Rotation script: `scripts/rotate_jwt_key.py`
- mTLS bootstrap: `scripts/bootstrap_mtls.sh`
