import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.config import settings
from app.token_broker import TokenBrokerClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["token-broker"])


# IMPORTANT: Single-user demo limitation
# These module-level globals create a process-wide singleton session.
# If User A and User B both try to use this backend concurrently:
#   - User B's session will overwrite User A's session
#   - User A's polling task will be cancelled
#   - User A will receive "No active session" errors
#
# For multi-user support, replace these globals with per-user session storage:
#   - Use a dict keyed by user_id: _sessions: dict[str, SessionData] = {}
#   - Or use Redis/database for production deployments
#   - Extract user_id from JWT or session cookie for each request
_client: TokenBrokerClient | None = None
_jwt: str | None = None
_event_queue: asyncio.Queue | None = None
_poll_task: asyncio.Task | None = None


def _get_client() -> TokenBrokerClient | None:
    global _client
    if _client is None and settings.token_broker_url:
        _client = TokenBrokerClient(settings.token_broker_url)
    return _client


async def _polling_loop(jwt: str, queue: asyncio.Queue) -> None:
    client = _get_client()
    if not client:
        return
    logger.info("Token Broker polling loop started")
    while True:
        try:
            event = await client.poll_events(jwt)
            if event is not None:
                logger.info(
                    f"Token Broker event received: {event.get('event_type', 'unknown')}"
                )
                await queue.put(event)
        except Exception as e:
            # On any error (including 404), send error event to frontend and stop polling
            logger.error(f"Token Broker polling error: {e}")
            error_event = {
                "event_type": "error",
                "error": str(e),
                "status_code": getattr(
                    getattr(e, "response", None), "status_code", None
                ),
            }
            await queue.put(error_event)
            break


async def _cleanup() -> None:
    global _jwt, _event_queue, _poll_task
    if _poll_task and not _poll_task.done():
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass
    _poll_task = None
    _event_queue = None
    _jwt = None


class SessionRequest(BaseModel):
    redirect_url: str


@router.post("/token-broker/session")
async def create_session(body: SessionRequest, request: Request):
    global _jwt, _event_queue, _poll_task

    client = _get_client()
    if not client:
        logger.warning("Token Broker session creation failed: not configured")
        return JSONResponse(
            content={"detail": "Token Broker not configured"},
            status_code=503,
        )

    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse(content={"detail": "Unauthorized"}, status_code=401)
    jwt = auth[7:]

    await _cleanup()

    # Sanitize user input to prevent log injection (remove newlines/carriage returns)
    safe_redirect_url = body.redirect_url.replace("\n", "").replace("\r", "")
    logger.info(
        "Creating Token Broker session with redirect_url: %s", safe_redirect_url
    )
    # Pass original URL — safe_redirect_url is only for log injection prevention
    ok = await client.create_session(jwt, body.redirect_url)
    if not ok:
        logger.error("Token Broker session creation failed: service unavailable")
        return JSONResponse(
            content={"detail": "Token Broker unavailable"},
            status_code=503,
        )

    _jwt = jwt
    _event_queue = asyncio.Queue()
    _poll_task = asyncio.create_task(_polling_loop(jwt, _event_queue))

    logger.info("Token Broker session created successfully, polling started")
    return JSONResponse(content={}, status_code=201)


@router.get("/token-broker/ui-events")
async def get_ui_events(request: Request):
    """Long-poll for Token Broker UI events (no timeout)."""
    if _event_queue is None:
        return JSONResponse(
            content={"detail": "No active session"},
            status_code=404,
        )

    # Wait indefinitely for an event from the queue
    event = await _event_queue.get()
    logger.info(
        f"Token Broker ui-event delivered: {event.get('event_type', 'unknown')}"
    )
    return JSONResponse(content=event)


@router.delete("/token-broker/session")
async def end_session(request: Request):
    logger.info("Ending Token Broker session")
    client = _get_client()
    if client and _jwt:
        await client.end_session(_jwt)
    await _cleanup()
    logger.info("Token Broker session ended successfully")
    return JSONResponse(content={}, status_code=200)
