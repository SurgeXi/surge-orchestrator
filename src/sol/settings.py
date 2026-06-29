"""Environment-driven configuration."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SOL_",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- core ----
    port: int = 9320
    host: str = "0.0.0.0"
    log_level: str = "info"
    environment: str = "production"

    # ---- enforcement ----
    enforce: bool = False
    shadow_enabled: bool = True
    # Auto-remediation lane (DEFAULT OFF). When true, a dispatch that
    # EXACTLY matches a curated remediation playbook (see
    # sol.policy.remediation) may be auto-approved instead of human-gated.
    # Off => Surge may only RECOMMEND; it never applies a remediation.
    # This is a SEPARATE flag from auto_readonly: it gates a tiny
    # allow-list of pre-vetted SAFE-WRITE remediations, not read-only ops.
    auto_remediation: bool = False

    # ---- database ----
    database_url: str = Field(
        default="postgresql+psycopg2://sol_user:CHANGEME@127.0.0.1:5432/surge_brain",
        description="SQLAlchemy URL for Brain Postgres (sol schema).",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # ---- auth ----
    jwt_admin_ttl_minutes: int = 60
    jwt_service_ttl_days: int = 90
    jwt_callback_ttl_minutes: int = 15
    callback_hmac_key_path: str = "/etc/sol/keys/callback_hmac.key"
    callback_base_url: str = "https://sol.surgexi.com"
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = False
    smtp_auth: bool = False
    smtp_enabled: bool = False
    smtp_from_address: str = "sol@surgexi.com"
    smtp_from_name: str = "Surge Orchestration Layer"
    smtp_timeout_seconds: int = 10
    jwt_signing_key_path: str = "/etc/sol/keys/jwt_signing.key"
    jwt_signing_pubkey_path: str = "/etc/sol/keys/jwt_signing.pub"
    # Rotation: SOL accepts JWTs signed by any *.pub in this dir; issues with current.
    jwt_keys_dir: str = "/etc/sol/keys"
    jwt_current_key_name: str = "current"  # current.key + current.pub
    service_tokens_file: str = "/etc/sol/service-tokens.env"

    # ---- mTLS (Phase 3 hardening) ----
    mtls_enabled: bool = False
    mtls_cert_path: str = "/etc/sol/server/sol-server.crt"
    mtls_key_path: str = "/etc/sol/server/sol-server.key"
    mtls_ca_path: str = "/etc/sol/ca/sol-ca.crt"
    mtls_port: int = 9321
    mtls_callers_yaml_path: str = "/etc/sol/mtls-callers.yaml"
    # Shared secret nginx echoes in X-SOL-Nginx-Token to prove origin.
    # If the file is missing, the secret check is skipped (legacy fallback).
    # File MUST be mode 640 root:todds.
    nginx_shared_secret_path: str = "/etc/sol/nginx-shared-secret"
    # Loopback IP check is a secondary defense — disabled by default because
    # uvicorn's proxy_headers middleware rewrites the apparent peer IP from
    # X-Forwarded-For. Enable for hardened environments where you've also
    # disabled proxy_headers in uvicorn.
    mtls_require_loopback: bool = False

    # ---- token revocation cache ----
    revoked_token_cache_ttl_seconds: int = 300  # 5 min

    # ---- policy ----
    policy_yaml_path: str = "/etc/sol/policy.yaml"
    policy_reload_interval_seconds: int = 60

    # ---- WAL (degraded mode) ----
    wal_dir: str = "/var/lib/sol/wal"
    wal_max_bytes: int = 1_073_741_824  # 1 GiB

    # ---- observability ----
    metrics_enabled: bool = True

    @property
    def is_shadow_only(self) -> bool:
        return self.shadow_enabled and not self.enforce


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
