"""
kagenti.identity.serviceaccount_provider

Kubernetes ServiceAccount identity provider implementation.
"""

import os
import jwt
from typing import Dict, Any

from .provider import WorkloadIdentity, IdentityProvider
from .exceptions import TokenNotFoundError, InvalidTokenError


class ServiceAccountIdentity(WorkloadIdentity):
    """Kubernetes ServiceAccount workload identity implementation."""

    def __init__(
        self, token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ):
        """
        Initialize ServiceAccount identity.

        Args:
            token_path: Path to the ServiceAccount token file
        """
        self.token_path = token_path
        self._token = None
        self._claims = None
        self._namespace = None
        self._service_account = None

    def _read_token(self) -> str:
        """Read the ServiceAccount token from file."""
        if self._token is None:
            if not os.path.exists(self.token_path):
                raise TokenNotFoundError(
                    f"ServiceAccount token not found at {self.token_path}. "
                    "Ensure the pod has a ServiceAccount configured."
                )

            try:
                with open(self.token_path, "r") as f:
                    self._token = f.read().strip()
            except IOError as e:
                raise TokenNotFoundError(
                    f"Failed to read ServiceAccount token from {self.token_path}: {e}"
                )

            if not self._token:
                raise TokenNotFoundError(
                    f"ServiceAccount token file {self.token_path} is empty"
                )

        return self._token

    def _read_namespace(self) -> str:
        """Read the namespace from the standard location."""
        if self._namespace is None:
            namespace_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
            try:
                with open(namespace_path, "r") as f:
                    self._namespace = f.read().strip()
            except IOError:
                # Fallback: try to get from environment
                self._namespace = os.environ.get("POD_NAMESPACE", "default")
        return self._namespace

    def _parse_claims(self) -> Dict[str, Any]:
        """Parse JWT claims from the ServiceAccount token."""
        if self._claims is None:
            token = self._read_token()
            try:
                # Decode without verification (Kubernetes validates these tokens)
                self._claims = jwt.decode(token, options={"verify_signature": False})
            except jwt.DecodeError as e:
                raise InvalidTokenError(
                    f"Failed to decode ServiceAccount JWT token: {e}"
                )

        return self._claims

    def get_subject(self) -> str:
        """
        Extract subject from ServiceAccount token.

        Returns:
            ServiceAccount subject in format: system:serviceaccount:<namespace>:<name>
        """
        claims = self._parse_claims()

        # ServiceAccount tokens have 'sub' claim in format: system:serviceaccount:<ns>:<name>
        if "sub" in claims:
            return claims["sub"]

        # Fallback: construct from namespace and service account name
        # This is less reliable but provides a fallback
        namespace = self._read_namespace()
        # Try to extract service account name from token claims or use component name
        # For now, we'll use a generic format
        # In practice, the service account name should be known from the pod spec
        return f"system:serviceaccount:{namespace}:default"

    def get_token(self) -> str:
        """Return the raw ServiceAccount JWT token."""
        return self._read_token()

    def get_claims(self) -> Dict[str, Any]:
        """Return all claims from the ServiceAccount JWT token."""
        claims = self._parse_claims().copy()

        # Add namespace if not already in claims
        if "namespace" not in claims:
            claims["namespace"] = self._read_namespace()

        return claims


class ServiceAccountProvider(IdentityProvider):
    """Kubernetes ServiceAccount identity provider."""

    def __init__(
        self, token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ):
        """
        Initialize ServiceAccount provider.

        Args:
            token_path: Path to the ServiceAccount token file
        """
        self.token_path = token_path

    def get_name(self) -> str:
        """Return provider name."""
        return "serviceaccount"

    def get_current_identity(self) -> WorkloadIdentity:
        """Get the current workload's ServiceAccount identity."""
        return ServiceAccountIdentity(token_path=self.token_path)

    def get_manifest_patches(self, component_name: str) -> Dict[str, Any]:
        """
        Return Kubernetes manifest patches for ServiceAccount token volumes.

        Args:
            component_name: Name of the component (used as ServiceAccount name)

        Returns:
            Dictionary with serviceAccountName, volumes, and volumeMounts

        Note:
            Uses standard Kubernetes token location for better compatibility.
            The projected token will be mounted at the standard location.
        """
        return {
            "serviceAccountName": component_name,
            "volumes": [
                {
                    "name": "kagenti-identity-token",
                    "projected": {
                        "sources": [
                            {
                                "serviceAccountToken": {
                                    "path": "token",
                                    "expirationSeconds": 3600,
                                    "audience": "kagenti",
                                }
                            }
                        ]
                    },
                }
            ],
            "volumeMounts": [
                {
                    "name": "kagenti-identity-token",
                    "mountPath": "/var/run/secrets/kubernetes.io/serviceaccount",
                    "readOnly": True,
                }
            ],
        }
