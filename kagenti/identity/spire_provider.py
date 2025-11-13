"""
kagenti.identity.spire_provider

SPIRE/SPIFFE identity provider implementation.
"""

import os
import jwt
from typing import Dict, Any

from .provider import WorkloadIdentity, IdentityProvider
from .exceptions import TokenNotFoundError, InvalidTokenError


class SPIREIdentity(WorkloadIdentity):
    """SPIRE workload identity implementation."""

    def __init__(self, token_path: str = "/opt/jwt_svid.token"):
        """
        Initialize SPIRE identity.

        Args:
            token_path: Path to the SPIRE JWT token file
        """
        self.token_path = token_path
        self._token = None
        self._claims = None

    def _read_token(self) -> str:
        """Read the SPIRE token from file."""
        if self._token is None:
            if not os.path.exists(self.token_path):
                raise TokenNotFoundError(
                    f"SPIRE token not found at {self.token_path}. "
                    "Ensure SPIRE is configured and the token is available."
                )

            try:
                with open(self.token_path, "r") as f:
                    self._token = f.read().strip()
            except IOError as e:
                raise TokenNotFoundError(
                    f"Failed to read SPIRE token from {self.token_path}: {e}"
                )

            if not self._token:
                raise TokenNotFoundError(f"SPIRE token file {self.token_path} is empty")

        return self._token

    def _parse_claims(self) -> Dict[str, Any]:
        """Parse JWT claims from the token."""
        if self._claims is None:
            token = self._read_token()
            try:
                # Decode without verification (signature verification handled by SPIRE)
                self._claims = jwt.decode(token, options={"verify_signature": False})
            except jwt.DecodeError as e:
                raise InvalidTokenError(f"Failed to decode SPIRE JWT token: {e}")

        return self._claims

    def get_subject(self) -> str:
        """Extract SPIFFE ID from the 'sub' claim."""
        claims = self._parse_claims()
        if "sub" not in claims:
            raise InvalidTokenError("SPIRE JWT token does not contain a 'sub' claim")
        return claims["sub"]

    def get_token(self) -> str:
        """Return the raw SPIRE JWT token."""
        return self._read_token()

    def get_claims(self) -> Dict[str, Any]:
        """Return all claims from the SPIRE JWT token."""
        return self._parse_claims().copy()


class SPIREProvider(IdentityProvider):
    """SPIRE identity provider."""

    def __init__(self, token_path: str = "/opt/jwt_svid.token"):
        """
        Initialize SPIRE provider.

        Args:
            token_path: Path to the SPIRE JWT token file
        """
        self.token_path = token_path

    def get_name(self) -> str:
        """Return provider name."""
        return "spire"

    def get_current_identity(self) -> WorkloadIdentity:
        """Get the current workload's SPIRE identity."""
        return SPIREIdentity(token_path=self.token_path)

    def get_manifest_patches(self, component_name: str) -> Dict[str, Any]:
        """
        Return Kubernetes manifest patches for SPIRE volumes.

        Args:
            component_name: Name of the component (not used for SPIRE)

        Returns:
            Dictionary with volumes and volumeMounts for SPIRE CSI driver
        """
        return {
            "volumes": [
                {
                    "name": "spiffe-workload-api",
                    "csi": {"driver": "csi.spiffe.io", "readOnly": True},
                }
            ],
            "volumeMounts": [
                {
                    "name": "spiffe-workload-api",
                    "mountPath": "/spiffe-workload-api",
                    "readOnly": True,
                }
            ],
        }
