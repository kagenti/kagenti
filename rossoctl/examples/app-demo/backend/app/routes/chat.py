import json
import logging
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@router.post("/chat/{namespace}/{name}/send")
async def send_message(
    namespace: str,
    name: str,
    body: ChatRequest,
    request: Request,
):
    """Use the Rossoctl streaming endpoint, accumulate all chunks,
    and return a single JSON response."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    auth = request.headers.get("authorization")
    if auth:
        headers["Authorization"] = auth

    upstream = httpx.AsyncClient(
        base_url=settings.rossoctl_api_url,
        timeout=httpx.Timeout(120.0, connect=10.0),
    )

    try:
        resp = await upstream.send(
            upstream.build_request(
                "POST",
                f"/api/v1/chat/{quote(namespace, safe='')}/{quote(name, safe='')}/stream",
                json=body.model_dump(exclude_none=True),
                headers=headers,
            ),
            stream=True,
        )
    except httpx.RequestError as e:
        await upstream.aclose()
        logger.error("Cannot connect to Rossoctl backend: %s", e)
        return JSONResponse(
            content={"detail": "Cannot connect to upstream"},
            status_code=503,
        )

    if resp.status_code >= 400:
        try:
            await resp.aread()
            detail = resp.text[:500]
        except Exception:
            detail = str(resp.status_code)
        await resp.aclose()
        await upstream.aclose()
        return JSONResponse(
            content={"detail": detail},
            status_code=resp.status_code,
        )

    content_parts: list[str] = []
    error_msg: str | None = None
    session_id = body.session_id or ""

    try:
        async for line in resp.aiter_lines():
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            if chunk.get("session_id"):
                session_id = chunk["session_id"]

            if chunk.get("error"):
                error_msg = chunk["error"]
                break

            text = chunk.get("content", "")
            if text:
                content_parts.append(text)
    finally:
        await resp.aclose()
        await upstream.aclose()

    if error_msg:
        return JSONResponse(
            content={"detail": error_msg},
            status_code=502,
        )

    return JSONResponse(
        content={
            "content": "\n".join(content_parts)
            if content_parts
            else "No response from agent",
            "session_id": session_id,
            "is_complete": True,
        }
    )
