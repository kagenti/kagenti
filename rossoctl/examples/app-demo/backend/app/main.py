import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import agents, auth_config, chat, token_broker

# Configure logging with timestamps
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(
        base_url=settings.rossoctl_api_url,
        timeout=httpx.Timeout(65.0, connect=10.0),
    )
    yield
    await app.state.http_client.aclose()


app = FastAPI(
    title="Rossoctl App Demo",
    description="Demo application showing Rossoctl platform integration",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_config.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(token_broker.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    return {"status": "ok"}
