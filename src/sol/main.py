"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from .admin import router as admin_router
from .api import approvals, audit, capabilities, dispatch, health, policies
from .observability.logging import configure_logging, get_logger
from .observability.metrics import init_metrics
from .policy.cache import PolicyCache
from .settings import get_settings

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.log_level)
    init_metrics()
    cache = PolicyCache()
    cache.load_from_yaml(s.policy_yaml_path)
    app.state.policy_cache = cache
    log.info(
        "sol.startup",
        port=s.port,
        enforce=s.enforce,
        shadow_enabled=s.shadow_enabled,
        environment=s.environment,
    )
    yield
    log.info("sol.shutdown")


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Surge Orchestration Layer",
        version="0.1.0",
        description="Unified dispatch + policy + audit surface.",
        lifespan=lifespan,
        docs_url="/docs" if s.environment != "production" else None,
        redoc_url=None,
    )

    app.include_router(health.router)
    app.include_router(dispatch.router, prefix="/v1/sol")
    app.include_router(capabilities.router, prefix="/v1/sol")
    app.include_router(approvals.router, prefix="/v1/sol")
    app.include_router(audit.router, prefix="/v1/sol")
    app.include_router(policies.router, prefix="/v1/sol")
    app.include_router(admin_router.router)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
