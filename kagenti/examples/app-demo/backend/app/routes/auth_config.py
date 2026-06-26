from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["auth"])


@router.get("/auth/config")
async def get_auth_config():
    if not settings.enable_auth:
        return {"enabled": False, "token_broker_enabled": False}
    return {
        "enabled": True,
        "keycloak_url": settings.keycloak_public_url,
        "realm": settings.keycloak_realm,
        "client_id": settings.client_id,
        "token_broker_enabled": bool(settings.token_broker_url),
    }
