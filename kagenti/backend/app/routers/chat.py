# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
A2A Chat API endpoints.

Provides endpoints for chatting with A2A agents using the Agent-to-Agent protocol.
"""

import logging
from typing import Optional, List, Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

# A2A protocol constants
A2A_AGENT_CARD_PATH = "/.well-known/agent.json"


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
    - Off-cluster (local dev): http://{name}.{domain}:8080
    """
    if settings.is_running_in_cluster:
        # In-cluster: use Kubernetes service DNS
        return f"http://{name}.{namespace}.svc.cluster.local:8080"
    else:
        # Off-cluster: use external domain (e.g., localtest.me)
        domain = settings.domain_name
        return f"http://{name}.{domain}:8080"


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
) -> ChatResponse:
    """
    Send a message to an A2A agent and get the response.

    This endpoint sends a message using the A2A protocol and returns
    the agent's response. For streaming agents, use the /stream endpoint.
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

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                agent_url,
                json=message_payload,
                headers={"Content-Type": "application/json"},
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


async def _stream_a2a_response(agent_url: str, message: str, session_id: str):
    """Generator for streaming A2A responses."""
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

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                agent_url,
                json=message_payload,
                headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            ) as response:
                response.raise_for_status()
                logger.info(f"Connected to agent, status={response.status_code}")

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    logger.debug(f"Received line: {line[:200]}")  # Log first 200 chars

                    # Parse SSE format
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            logger.info("Received [DONE] signal from agent")
                            yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
                            break

                        try:
                            chunk = json.loads(data)
                            logger.debug(f"Parsed chunk: {json.dumps(chunk, indent=2)[:500]}")

                            # Extract text content from various A2A response formats
                            content = ""
                            should_send = False

                            if "result" in chunk:
                                result = chunk["result"]

                                # TaskArtifactUpdateEvent - always send artifacts
                                if "artifact" in result:
                                    logger.info("Processing TaskArtifactUpdateEvent")
                                    artifact = result.get("artifact", {})
                                    logger.debug(
                                        f"Artifact structure: {json.dumps(artifact, indent=2)[:1000]}"
                                    )
                                    parts = artifact.get("parts", [])
                                    logger.info(f"Artifact has {len(parts)} parts")
                                    for i, part in enumerate(parts):
                                        logger.info(
                                            f"Part {i} full structure: {json.dumps(part, default=str)[:500]}"
                                        )

                                        # Handle simple text field
                                        if isinstance(part, dict) and "text" in part:
                                            content += part["text"]
                                            should_send = True
                                            logger.info(
                                                f"Extracted text from part {i}: {part['text'][:100]}"
                                            )

                                        # Handle kind=text format
                                        elif (
                                            isinstance(part, dict)
                                            and "kind" in part
                                            and part["kind"] == "text"
                                        ):
                                            text = part.get("text", "")
                                            content += text
                                            should_send = True
                                            logger.info(
                                                f"Extracted text from part {i} (kind=text): {text[:100]}"
                                            )

                                        # Handle data field (for JSON, images, etc.)
                                        elif isinstance(part, dict) and "data" in part:
                                            data = part["data"]
                                            kind = part.get("kind", "unknown")

                                            logger.info(
                                                f"Part {i} has data field: kind={kind}, data_type={type(data).__name__}"
                                            )

                                            # Check if data is a wrapper with content_type/content fields
                                            # OR if data is the actual content itself
                                            if isinstance(data, dict):
                                                # Check if it's a metadata wrapper (has content_type and content)
                                                if "content_type" in data and "content" in data:
                                                    content_type = data.get("content_type", "")
                                                    content_value = data.get("content", "")
                                                    logger.info(
                                                        f"Part {i} has wrapped content: content_type={content_type}"
                                                    )

                                                    if (
                                                        content_type == "application/json"
                                                        and content_value
                                                    ):
                                                        try:
                                                            json_data = json.loads(content_value)
                                                            formatted_json = json.dumps(
                                                                json_data, indent=2
                                                            )
                                                            content += f"\n```json\n{formatted_json}\n```\n"
                                                            should_send = True
                                                            logger.info(
                                                                f"Extracted JSON from wrapped content: {formatted_json[:200]}"
                                                            )
                                                        except json.JSONDecodeError as e:
                                                            logger.warning(
                                                                f"Failed to parse JSON: {e}"
                                                            )
                                                            content += f"\n{content_value}\n"
                                                            should_send = True
                                                    elif content_type.startswith("image/"):
                                                        logger.info(
                                                            "Image data detected (skipping)"
                                                        )
                                                    else:
                                                        content += f"\n{content_value}\n"
                                                        should_send = True
                                                else:
                                                    # Data IS the actual content (not wrapped)
                                                    logger.info(
                                                        f"Part {i} data IS the content (not wrapped)"
                                                    )
                                                    formatted_json = json.dumps(data, indent=2)
                                                    content += f"\n```json\n{formatted_json}\n```\n"
                                                    should_send = True
                                                    logger.info(
                                                        f"Extracted direct JSON object: {formatted_json[:200]}"
                                                    )

                                            elif isinstance(data, (list, str, int, float, bool)):
                                                # Data is a primitive type or list
                                                logger.info(
                                                    f"Part {i} data is primitive type: {type(data).__name__}"
                                                )
                                                if isinstance(data, str):
                                                    # Try to parse as JSON
                                                    try:
                                                        json_data = json.loads(data)
                                                        formatted_json = json.dumps(
                                                            json_data, indent=2
                                                        )
                                                        content += (
                                                            f"\n```json\n{formatted_json}\n```\n"
                                                        )
                                                        should_send = True
                                                        logger.info(
                                                            f"Parsed string as JSON: {formatted_json[:200]}"
                                                        )
                                                    except (json.JSONDecodeError, TypeError):
                                                        # Not JSON, use as plain text
                                                        content += f"\n{data}\n"
                                                        should_send = True
                                                        logger.info(
                                                            f"Using as plain text: {str(data)[:200]}"
                                                        )
                                                else:
                                                    # List or other primitive
                                                    formatted = json.dumps(data, indent=2)
                                                    content += f"\n```json\n{formatted}\n```\n"
                                                    should_send = True
                                                    logger.info(
                                                        f"Formatted primitive as JSON: {formatted[:200]}"
                                                    )

                                # TaskStatusUpdateEvent - only send if final
                                elif "status" in result and "taskId" in result:
                                    status = result["status"]
                                    is_final = result.get("final", False)
                                    state = status.get("state", "N/A")
                                    logger.info(
                                        f"Processing TaskStatusUpdateEvent: taskId={result.get('taskId')}, state={state}, final={is_final}"
                                    )
                                    logger.debug(
                                        f"Status structure: {json.dumps(status, default=str, indent=2)[:1000]}"
                                    )

                                    # Check for final state
                                    if is_final or status.get("state") in ["COMPLETED", "FAILED"]:
                                        if "message" in status and status["message"]:
                                            message = status["message"]
                                            logger.debug(
                                                f"Status message structure: {json.dumps(message, default=str)[:500]}"
                                            )
                                            parts = message.get("parts", [])
                                            logger.info(f"TaskStatusUpdate has {len(parts)} parts")
                                            for i, part in enumerate(parts):
                                                logger.debug(
                                                    f"Part {i}: {json.dumps(part, default=str)[:300]}"
                                                )
                                                if isinstance(part, dict):
                                                    if "text" in part:
                                                        text = part["text"]
                                                        content += text
                                                        should_send = True
                                                        logger.info(
                                                            f"Extracted text from part {i}: {text[:100]}"
                                                        )
                                                    elif "kind" in part and part["kind"] == "text":
                                                        text = part.get("text", "")
                                                        content += text
                                                        should_send = True
                                                        logger.info(
                                                            f"Extracted text from part {i} (kind=text): {text[:100]}"
                                                        )
                                        else:
                                            logger.warning(
                                                f"TaskStatusUpdate has no message or message is None"
                                            )
                                    else:
                                        logger.debug(
                                            f"Skipping non-final TaskStatusUpdate (state={state})"
                                        )

                                # Task object (initial task response)
                                elif "id" in result and "status" in result:
                                    task_status = result["status"]
                                    state = task_status.get("state", "")
                                    logger.info(
                                        f"Processing Task object: id={result.get('id')}, state={state}"
                                    )

                                    # Only send final task states
                                    if state in ["COMPLETED", "FAILED"]:
                                        if "message" in task_status and task_status["message"]:
                                            parts = task_status["message"].get("parts", [])
                                            logger.debug(f"Task has {len(parts)} parts")
                                            for part in parts:
                                                if isinstance(part, dict):
                                                    if "text" in part:
                                                        content += part["text"]
                                                        should_send = True
                                                    elif "kind" in part and part["kind"] == "text":
                                                        content += part.get("text", "")
                                                        should_send = True
                                    else:
                                        logger.debug(f"Skipping non-final Task (state={state})")

                                # Direct message
                                elif "parts" in result:
                                    logger.info("Processing direct message with parts")
                                    for part in result["parts"]:
                                        if isinstance(part, dict):
                                            if "text" in part:
                                                content += part["text"]
                                                should_send = True
                                            elif "kind" in part and part["kind"] == "text":
                                                content += part.get("text", "")
                                                should_send = True

                                else:
                                    logger.warning(
                                        f"Unknown result structure: keys={list(result.keys())}"
                                    )

                            # Send content if we extracted any
                            if content and should_send:
                                logger.info(
                                    f"Yielding content (length={len(content)}): {content[:100]}..."
                                )
                                yield f"data: {json.dumps({'content': content, 'session_id': session_id})}\n\n"
                            elif "result" in chunk:
                                logger.debug(
                                    f"No content extracted from chunk with result keys: {list(chunk['result'].keys())}"
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
):
    """
    Send a message to an A2A agent and stream the response.

    This endpoint uses Server-Sent Events (SSE) to stream the agent's
    response in real-time. Requires an agent that supports streaming.
    """
    agent_url = _get_agent_url(name, namespace)
    session_id = request.session_id or uuid4().hex

    return StreamingResponse(
        _stream_a2a_response(agent_url, request.message, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
