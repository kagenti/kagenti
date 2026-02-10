# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Authentication and authorization utilities.

Supports JWT token validation with Keycloak.
"""

import logging
from typing import Optional, List

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, jwk
from jose.exceptions import JWKError
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# HTTP Bearer token security scheme
security = HTTPBearer(auto_error=False)

# =============================================================================
# RBAC Role Constants
# =============================================================================
# These roles are defined in Keycloak and embedded in JWT realm_access.roles

ROLE_VIEWER = "kagenti-viewer"
ROLE_OPERATOR = "kagenti-operator"
ROLE_ADMIN = "kagenti-admin"

# Role hierarchy: higher roles inherit permissions of lower roles
# e.g., kagenti-admin can do everything kagenti-operator and kagenti-viewer can do
ROLE_HIERARCHY: dict[str, list[str]] = {
    ROLE_ADMIN: [ROLE_OPERATOR, ROLE_VIEWER],
    ROLE_OPERATOR: [ROLE_VIEWER],
    ROLE_VIEWER: [],
}


def get_effective_roles(roles: list[str]) -> set[str]:
    """
    Expand a list of roles to include all inherited roles.

    Args:
        roles: List of role names from the token

    Returns:
        Set of all effective roles (including inherited ones)
    """
    effective = set(roles)
    for role in roles:
        if role in ROLE_HIERARCHY:
            effective.update(ROLE_HIERARCHY[role])
    return effective


class KeycloakJWKS:
    """Manages Keycloak JWKS (JSON Web Key Set) for token validation."""

    def __init__(self, keycloak_url: str, realm: str):
        self.jwks_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/certs"
        self._keys: dict = {}
        self._loaded = False

    async def load_keys(self) -> None:
        """Fetch JWKS from Keycloak."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.jwks_url, timeout=10.0)
                response.raise_for_status()
                jwks_data = response.json()
                self._keys = {key["kid"]: key for key in jwks_data.get("keys", [])}
                self._loaded = True
                logger.info(f"Loaded {len(self._keys)} keys from Keycloak JWKS")
        except Exception as e:
            logger.error(f"Failed to load JWKS from {self.jwks_url}: {e}")
            raise

    def get_key(self, kid: str) -> Optional[dict]:
        """Get a specific key by its ID."""
        return self._keys.get(kid)

    @property
    def is_loaded(self) -> bool:
        return self._loaded


# Global JWKS instance
_jwks: Optional[KeycloakJWKS] = None


def get_jwks() -> KeycloakJWKS:
    """Get or create the JWKS instance."""
    global _jwks
    if _jwks is None:
        _jwks = KeycloakJWKS(
            keycloak_url=settings.effective_keycloak_url,
            realm=settings.effective_keycloak_realm,
        )
    return _jwks


class TokenData:
    """Parsed and validated token data."""

    def __init__(
        self,
        sub: str,
        username: str,
        email: Optional[str],
        roles: List[str],
        raw_token: dict,
    ):
        self.sub = sub
        self.username = username
        self.email = email
        self.roles = roles
        self.raw_token = raw_token

    def has_role(self, role: str) -> bool:
        """
        Check if user has a specific role, considering role hierarchy.

        Args:
            role: The role to check for

        Returns:
            True if user has the role directly or via hierarchy inheritance
        """
        effective_roles = get_effective_roles(self.roles)
        return role in effective_roles


async def validate_token(token: str) -> TokenData:
    """
    Validate a JWT token against Keycloak.

    Args:
        token: The JWT token string

    Returns:
        TokenData with parsed claims

    Raises:
        HTTPException: If token is invalid
    """
    try:
        # Decode header to get the key ID
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing key ID",
            )

        # Get JWKS and load if needed
        jwks = get_jwks()
        if not jwks.is_loaded:
            await jwks.load_keys()

        # Get the signing key
        key_data = jwks.get_key(kid)
        if not key_data:
            # Try reloading keys in case they rotated
            await jwks.load_keys()
            key_data = jwks.get_key(kid)
            if not key_data:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token signing key not found",
                )

        # Construct the public key
        public_key = jwk.construct(key_data)

        # Verify and decode the token
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={
                "verify_aud": False,  # Keycloak doesn't always set audience
                "verify_exp": True,
            },
        )

        # Extract user information
        sub = payload.get("sub", "")
        username = payload.get("preferred_username", payload.get("sub", "unknown"))
        email = payload.get("email")

        # Extract roles from realm and resource access
        roles = []
        realm_access = payload.get("realm_access", {})
        roles.extend(realm_access.get("roles", []))

        resource_access = payload.get("resource_access", {})
        for resource_roles in resource_access.values():
            if isinstance(resource_roles, dict):
                roles.extend(resource_roles.get("roles", []))

        return TokenData(
            sub=sub,
            username=username,
            email=email,
            roles=list(set(roles)),  # Deduplicate
            raw_token=payload,
        )

    except JWTError as e:
        logger.warning(f"JWT validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )
    except JWKError as e:
        logger.warning(f"JWK error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token key error",
        )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[TokenData]:
    """
    Dependency to get the current authenticated user.

    Returns None if no token is provided (for optional auth).
    Raises HTTPException if token is invalid.
    """
    if not settings.enable_auth:
        # Auth disabled - return mock user
        return TokenData(
            sub="mock-user",
            username="admin",
            email="admin@example.com",
            roles=[ROLE_ADMIN],
            raw_token={},
        )

    if credentials is None:
        return None

    return await validate_token(credentials.credentials)


async def get_required_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    """
    Dependency to require authentication.

    Raises HTTPException if no valid token is provided.
    """
    if not settings.enable_auth:
        # Auth disabled - return mock user
        return TokenData(
            sub="mock-user",
            username="admin",
            email="admin@example.com",
            roles=[ROLE_ADMIN],
            raw_token={},
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await validate_token(credentials.credentials)


def require_roles(*required_roles: str):
    """
    Dependency factory to require specific roles.

    Supports role hierarchy: if a user has kagenti-admin, they automatically
    satisfy requirements for kagenti-operator or kagenti-viewer.

    Usage:
        @router.get("/protected", dependencies=[Depends(require_roles(ROLE_VIEWER))])
        async def view_endpoint():
            ...

        @router.post("/create", dependencies=[Depends(require_roles(ROLE_OPERATOR))])
        async def create_endpoint():
            ...
    """

    async def role_checker(user: TokenData = Depends(get_required_user)) -> TokenData:
        if not settings.enable_auth:
            return user

        for role in required_roles:
            if user.has_role(role):
                return user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Required role(s): {', '.join(required_roles)}",
        )

    return role_checker
