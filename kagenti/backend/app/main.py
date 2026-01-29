# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Kagenti Backend API - FastAPI Application

This module provides the REST API backend for the Kagenti UI,
exposing endpoints for managing agents, tools, and platform configuration.
"""

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


from app.core.config import settings
from app.routers import agents, tools, namespaces, config, auth, chat

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
    yield
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
