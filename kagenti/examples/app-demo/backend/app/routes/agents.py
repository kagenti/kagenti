from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["agents"])


async def _proxy_get(request: Request, path: str) -> JSONResponse:
    client = request.app.state.http_client
    headers = {}
    auth = request.headers.get("authorization")
    if auth:
        headers["Authorization"] = auth
    resp = await client.get(path, headers=headers)
    return JSONResponse(content=resp.json(), status_code=resp.status_code)


@router.get("/namespaces")
async def list_namespaces(request: Request):
    return await _proxy_get(request, "/api/v1/namespaces")


@router.get("/agents")
async def list_agents(request: Request, namespace: str = ""):
    """List all agents. Access is enforced at chat time."""
    path = (
        f"/api/v1/agents?namespace={quote(namespace, safe='')}"
        if namespace
        else "/api/v1/agents"
    )
    return await _proxy_get(request, path)
