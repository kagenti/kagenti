# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Kagenti Backend API - FastAPI Application

This module provides the REST API backend for the Kagenti UI,
exposing endpoints for managing agents, tools, and platform configuration.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Middleware to prevent browser caching of API responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        # Add no-cache headers to API endpoints to prevent stale data
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


from app.core.config import settings  # pylint: disable=wrong-import-position
from app.routers import (  # pylint: disable=wrong-import-position
    agents,
    tools,
    namespaces,
    config,
    auth,
    chat,
    shipwright,
)

# Conditionally import feature-flagged modules.
# pylint: disable=wrong-import-position,no-name-in-module,import-error
_sandbox_modules_loaded = False
if settings.kagenti_feature_flag_sandbox:
    try:
        from app.routers import (  # noqa: E402
            sandbox,
            sandbox_deploy,
            sandbox_files,
            token_usage,
            sidecar,
            events,
            models,
            llm_keys,
        )
        from app.services.session_db import close_all_pools  # noqa: E402

        _sandbox_modules_loaded = True
    except ImportError:
        logging.getLogger(__name__).warning(
            "SANDBOX flag enabled but sandbox modules not installed — skipping"
        )

_triggers_modules_loaded = False
if settings.kagenti_feature_flag_triggers:
    try:
        from app.routers import sandbox_trigger  # noqa: E402

        _triggers_modules_loaded = True
    except ImportError:
        logging.getLogger(__name__).warning(
            "TRIGGERS flag enabled but trigger modules not installed — skipping"
        )

_integrations_modules_loaded = False
if settings.kagenti_feature_flag_integrations:
    try:
        from app.routers import integrations  # noqa: E402

        _integrations_modules_loaded = True
    except ImportError:
        logging.getLogger(__name__).warning(
            "INTEGRATIONS flag enabled but integration modules not installed — skipping"
        )
_skills_modules_loaded = False
if settings.kagenti_feature_flag_skills:
    try:
        from app.routers import skills  # noqa: E402

        _skills_modules_loaded = True
    except ImportError:
        logging.getLogger(__name__).warning(
            "SKILLS flag enabled but skills modules not installed — skipping"
        )
# pylint: enable=wrong-import-position,no-name-in-module,import-error

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    logger.info("Starting Kagenti Backend API")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Domain: {settings.domain_name}")
    logger.info(f"ENABLE_AUTH environment variable set to: {settings.enable_auth}")

    # Start build reconciliation loop
    reconciliation_task = None
    if settings.enable_build_reconciliation:
        from app.services.reconciliation import run_reconciliation_loop

        reconciliation_task = asyncio.create_task(run_reconciliation_loop())
        logger.info(
            "Build reconciliation started (interval: %ds)",
            settings.build_reconciliation_interval,
        )
    else:
        logger.info("Build reconciliation disabled (ENABLE_BUILD_RECONCILIATION=false)")

    yield

    # Stop reconciliation
    if reconciliation_task:
        reconciliation_task.cancel()
        try:
            await reconciliation_task
        except asyncio.CancelledError:
            pass

    # Shutdown sandbox services (only if enabled and loaded)
    if _sandbox_modules_loaded:
        from app.services.sidecar_manager import get_sidecar_manager  # pylint: disable=import-error,no-name-in-module

        await get_sidecar_manager().shutdown()

        # Close session DB pools
        await close_all_pools()  # pylint: disable=used-before-assignment

    logger.info("Shutting down Kagenti Backend API")


app = FastAPI(
    title="Kagenti Backend API",
    description="REST API for the Kagenti Cloud Native Agent Platform UI",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prevent browser caching of API responses
app.add_middleware(NoCacheMiddleware)

# Include routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(namespaces.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(config.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(shipwright.router, prefix="/api/v1")

# Feature-flagged routers (variables are assigned inside try/except blocks above;
# pylint cannot track that _*_modules_loaded guards their usage).
# pylint: disable=used-before-assignment
if _sandbox_modules_loaded:
    app.include_router(sandbox.router, prefix="/api/v1")
    app.include_router(sandbox_deploy.router, prefix="/api/v1")
    app.include_router(sandbox_files.router, prefix="/api/v1")
    app.include_router(token_usage.router, prefix="/api/v1")
    app.include_router(sidecar.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(models.router, prefix="/api/v1")
    app.include_router(llm_keys.router, prefix="/api/v1")
    logger.info("Feature flag SANDBOX enabled — sandbox routes registered")

if _triggers_modules_loaded:
    app.include_router(sandbox_trigger.router, prefix="/api/v1")
    logger.info("Feature flag TRIGGERS enabled — trigger routes registered")

if _integrations_modules_loaded:
    app.include_router(integrations.router, prefix="/api/v1")
    logger.info("Feature flag INTEGRATIONS enabled — integration routes registered")

if _skills_modules_loaded:
    app.include_router(skills.router, prefix="/api/v1")
    logger.info("Feature flag SKILLS enabled — skills routes registered")
# pylint: enable=used-before-assignment


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/ready", tags=["health"])
async def readiness_check():
    """Readiness check endpoint."""
    # Could add kubernetes client connectivity check here
    return {"status": "ready"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
