# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
A2A Chat API endpoints.

Provides endpoints for chatting with A2A agents using the Agent-to-Agent protocol.
"""

import logging
from typing import Optional, List
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

# A2A protocol constants
A2A_AGENT_CARD_PATH = "/.well-known/agent-card.json"


class ChatMessage(BaseModel):
    """A chat message."""

    role: str  # "user" or "assistant"
    content: str


class AgentCardResponse(BaseModel):
    """Simplified agent card response."""

    name: str
    description: Optional[str] = None
    version: str
    url: str
    streaming: bool = False
    skills: List[dict] = []


class ChatRequest(BaseModel):
    """Request to chat with an A2A agent."""

    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Response from A2A agent chat."""

    content: str
    session_id: str
    is_complete: bool = True


def _get_agent_url(name: str, namespace: str) -> str:
    """Get the URL for an A2A agent.

    Returns different URL formats based on deployment context:
    - In-cluster: http://{name}.{namespace}.svc.cluster.local:8080
    - Off-cluster (local dev): http://{name}.{namespace}.{domain}:8080
    """
    if settings.is_running_in_cluster:
        # In-cluster: use Kubernetes service DNS
        return f"http://{name}.{namespace}.svc.cluster.local:8080"
    else:
        # Off-cluster: use external domain (e.g., localtest.me)
        domain = settings.domain_name
        return f"http://{name}.{namespace}.{domain}:8080"


@router.get("/{namespace}/{name}/agent-card", response_model=AgentCardResponse)
async def get_agent_card(
    namespace: str,
    name: str,
) -> AgentCardResponse:
    """
    Fetch the A2A agent card for an agent.

    The agent card describes the agent's capabilities, skills, and metadata.
    """
    agent_url = _get_agent_url(name, namespace)
    card_url = f"{agent_url}{A2A_AGENT_CARD_PATH}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(card_url)
            response.raise_for_status()
            card_data = response.json()

            # Parse capabilities
            capabilities = card_data.get("capabilities", {})
            streaming = capabilities.get("streaming", False)

            # Parse skills
            skills = []
            for skill in card_data.get("skills", []):
                skills.append(
                    {
                        "id": skill.get("id", ""),
                        "name": skill.get("name", ""),
                        "description": skill.get("description", ""),
                        "examples": skill.get("examples", []),
                    }
                )

            return AgentCardResponse(
                name=card_data.get("name", name),
                description=card_data.get("description"),
                version=card_data.get("version", "unknown"),
                url=card_data.get("url", agent_url),
                streaming=streaming,
                skills=skills,
            )

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching agent card: {e}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Failed to fetch agent card: {e.response.text}",
        )
    except httpx.RequestError as e:
        logger.error(f"Request error fetching agent card: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to agent at {agent_url}",
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching agent card: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching agent card: {str(e)}",
        )


@router.post("/{namespace}/{name}/send", response_model=ChatResponse)
async def send_message(
    namespace: str,
    name: str,
    request: ChatRequest,
    http_request: Request,
) -> ChatResponse:
    """
    Send a message to an A2A agent and get the response.

    This endpoint sends a message using the A2A protocol and returns
    the agent's response. For streaming agents, use the /stream endpoint.

    Forwards the Authorization header from the client to the agent for
    authenticated requests.
    """
    agent_url = _get_agent_url(name, namespace)
    session_id = request.session_id or uuid4().hex

    # Build A2A message payload
    message_payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": request.message}],
                "messageId": uuid4().hex,
            },
        },
    }

    # Prepare headers with optional Authorization
    headers = {"Content-Type": "application/json"}
    authorization = http_request.headers.get("Authorization")
    if authorization:
        headers["Authorization"] = authorization
        logger.info("Forwarding Authorization header to agent")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                agent_url,
                json=message_payload,
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()

            # Extract response content from A2A response
            content = ""
            if "result" in result:
                result_data = result["result"]
                # Handle Task response
                if "status" in result_data and "message" in result_data.get("status", {}):
                    parts = result_data["status"]["message"].get("parts", [])
                    for part in parts:
                        if isinstance(part, dict) and "text" in part:
                            content += part["text"]
                        elif hasattr(part, "text"):
                            content += part.text
                # Handle direct message response
                elif "parts" in result_data:
                    for part in result_data["parts"]:
                        if isinstance(part, dict) and "text" in part:
                            content += part["text"]

            if "error" in result:
                error = result["error"]
                content = f"Error: {error.get('message', 'Unknown error')}"

            return ChatResponse(
                content=content or "No response from agent",
                session_id=session_id,
                is_complete=True,
            )

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error sending message: {e}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Agent returned error: {e.response.text}",
        )
    except httpx.RequestError as e:
        logger.error(f"Request error sending message: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to agent at {agent_url}",
        )
    except Exception as e:
        logger.error(f"Unexpected error sending message: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error sending message: {str(e)}",
        )


def _extract_text_from_parts(parts: list) -> str:
    """Extract text content from A2A message parts."""
    import json as json_module

    content = ""
    for part in parts:
        if isinstance(part, dict):
            # Handle simple text field
            if "text" in part:
                content += part["text"]
            # Handle kind=text format
            elif part.get("kind") == "text":
                content += part.get("text", "")
            # Handle data field (for JSON, images, etc.)
            elif "data" in part:
                data = part["data"]
                if isinstance(data, dict):
                    if "content_type" in data and "content" in data:
                        content_type = data.get("content_type", "")
                        content_value = data.get("content", "")
                        if content_type == "application/json" and content_value:
                            try:
                                json_data = json_module.loads(content_value)
                                formatted = json_module.dumps(json_data, indent=2)
                                content += f"\n```json\n{formatted}\n```\n"
                            except json_module.JSONDecodeError:
                                content += f"\n{content_value}\n"
                        elif not content_type.startswith("image/"):
                            content += f"\n{content_value}\n"
                    else:
                        formatted = json_module.dumps(data, indent=2)
                        content += f"\n```json\n{formatted}\n```\n"
                elif isinstance(data, str):
                    try:
                        json_data = json_module.loads(data)
                        formatted = json_module.dumps(json_data, indent=2)
                        content += f"\n```json\n{formatted}\n```\n"
                    except (json_module.JSONDecodeError, TypeError):
                        content += f"\n{data}\n"
                elif isinstance(data, (list, int, float, bool)):
                    formatted = json_module.dumps(data, indent=2)
                    content += f"\n```json\n{formatted}\n```\n"
    return content


async def _stream_a2a_response(
    agent_url: str, message: str, session_id: str, authorization: Optional[str] = None
):
    """Generator for streaming A2A responses with event metadata."""
    import json

    # Build A2A streaming message payload
    message_payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "message/stream",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": message}],
                "messageId": uuid4().hex,
            },
        },
    }

    logger.info(f"Starting A2A stream to {agent_url} with session_id={session_id}")
    logger.debug(f"Message payload: {json.dumps(message_payload, indent=2)}")

    # Prepare headers with optional Authorization
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if authorization:
        headers["Authorization"] = authorization
        logger.info("Forwarding Authorization header to agent")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                agent_url,
                json=message_payload,
                headers=headers,
            ) as response:
                response.raise_for_status()
                logger.info(f"Connected to agent, status={response.status_code}")

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    logger.info(f"Received line from agent: {line[:300]}")

                    # Parse SSE format
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            logger.info("Received [DONE] signal from agent")
                            yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
                            break

                        try:
                            chunk = json.loads(data)
                            logger.info(f"Parsed chunk keys: {list(chunk.keys())}")
                            if "result" in chunk:
                                logger.info(f"Result keys: {list(chunk['result'].keys())}")

                            if "result" not in chunk:
                                logger.info("Skipping chunk - no 'result' field")
                                continue

                            result = chunk["result"]
                            payload = {"session_id": session_id}

                            # TaskArtifactUpdateEvent
                            if "artifact" in result:
                                logger.info("Processing TaskArtifactUpdateEvent")
                                artifact = result.get("artifact", {})
                                parts = artifact.get("parts", [])
                                content = _extract_text_from_parts(parts)

                                payload["event"] = {
                                    "type": "artifact",
                                    "taskId": result.get("taskId", ""),
                                    "name": artifact.get("name"),
                                    "index": artifact.get("index"),
                                }
                                if content:
                                    payload["content"] = content

                                logger.info(f"Yielding artifact event: {artifact.get('name')}")
                                yield f"data: {json.dumps(payload)}\n\n"

                            # TaskStatusUpdateEvent
                            elif "status" in result and "taskId" in result:
                                status = result["status"]
                                is_final = result.get("final", False)
                                state = status.get("state", "UNKNOWN")

                                logger.info(
                                    f"Processing TaskStatusUpdateEvent: taskId={result.get('taskId')}, "
                                    f"state={state}, final={is_final}"
                                )

                                # Extract status message text if present
                                status_message = ""
                                if "message" in status and status["message"]:
                                    parts = status["message"].get("parts", [])
                                    status_message = _extract_text_from_parts(parts)

                                payload["event"] = {
                                    "type": "status",
                                    "taskId": result.get("taskId", ""),
                                    "state": state,
                                    "final": is_final,
                                    "message": status_message if status_message else None,
                                }

                                # For final states, also include content for backward compatibility
                                if is_final or state in ["COMPLETED", "FAILED"]:
                                    if status_message:
                                        payload["content"] = status_message

                                logger.info(
                                    f"Yielding status event: state={state}, final={is_final}"
                                )
                                yield f"data: {json.dumps(payload)}\n\n"

                            # Task object (initial task response)
                            elif "id" in result and "status" in result:
                                task_status = result["status"]
                                state = task_status.get("state", "UNKNOWN")

                                logger.info(
                                    f"Processing Task object: id={result.get('id')}, state={state}"
                                )

                                payload["event"] = {
                                    "type": "status",
                                    "taskId": result.get("id", ""),
                                    "state": state,
                                    "final": state in ["COMPLETED", "FAILED"],
                                }

                                # Extract message content for final states
                                if state in ["COMPLETED", "FAILED"]:
                                    if "message" in task_status and task_status["message"]:
                                        parts = task_status["message"].get("parts", [])
                                        content = _extract_text_from_parts(parts)
                                        if content:
                                            payload["content"] = content

                                logger.info(f"Yielding task event: state={state}")
                                yield f"data: {json.dumps(payload)}\n\n"

                            # Direct message (A2AMessage)
                            elif "parts" in result:
                                logger.info("Processing direct message (A2AMessage) with parts")
                                content = _extract_text_from_parts(result["parts"])
                                message_id = result.get("messageId", "")

                                # Create an event for visibility in the events panel
                                payload["event"] = {
                                    "type": "status",
                                    "taskId": message_id,
                                    "state": "WORKING",
                                    "final": False,
                                    "message": content if content else None,
                                }
                                if content:
                                    payload["content"] = content

                                logger.info(
                                    f"Yielding direct message event: messageId={message_id}"
                                )
                                yield f"data: {json.dumps(payload)}\n\n"

                            else:
                                logger.warning(
                                    f"Unknown result structure: keys={list(result.keys())}"
                                )

                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse SSE data: {data[:200]}, error: {e}")
                            continue

    except httpx.HTTPStatusError as e:
        error_msg = f"Agent error: {e.response.status_code}"
        logger.error(f"{error_msg}: {e.response.text[:500]}")
        yield f"data: {json.dumps({'error': error_msg, 'session_id': session_id})}\n\n"
    except httpx.RequestError as e:
        error_msg = f"Connection error: {str(e)}"
        logger.error(error_msg)
        yield f"data: {json.dumps({'error': error_msg, 'session_id': session_id})}\n\n"
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        yield f"data: {json.dumps({'error': error_msg, 'session_id': session_id})}\n\n"


@router.post("/{namespace}/{name}/stream")
async def stream_message(
    namespace: str,
    name: str,
    request: ChatRequest,
    http_request: Request,
):
    """
    Send a message to an A2A agent and stream the response.

    This endpoint uses Server-Sent Events (SSE) to stream the agent's
    response in real-time. Requires an agent that supports streaming.

    Forwards the Authorization header from the client to the agent for
    authenticated requests.
    """
    agent_url = _get_agent_url(name, namespace)
    session_id = request.session_id or uuid4().hex

    # Extract Authorization header if present
    authorization = http_request.headers.get("Authorization")

    return StreamingResponse(
        _stream_a2a_response(agent_url, request.message, session_id, authorization),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
