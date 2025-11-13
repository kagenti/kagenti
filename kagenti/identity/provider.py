"""
kagenti.identity.provider

Abstract base classes for workload identity providers.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any


class WorkloadIdentity(ABC):
    """Represents a workload's identity."""

    @abstractmethod
    def get_subject(self) -> str:
        """
        Returns the identity subject (e.g., SPIFFE ID or ServiceAccount name).

        Returns:
            str: The identity subject identifier

        Raises:
            InvalidTokenError: If the token cannot be parsed or is invalid
        """
        pass

    @abstractmethod
    def get_token(self) -> str:
        """
        Returns a token representing this identity.

        Returns:
            str: The raw token string

        Raises:
            TokenNotFoundError: If the token cannot be read
        """
        pass

    @abstractmethod
    def get_claims(self) -> Dict[str, Any]:
        """
        Returns identity claims as a dictionary.

        Returns:
            Dict[str, Any]: Dictionary of claims from the identity token

        Raises:
            InvalidTokenError: If the token cannot be parsed
        """
        pass


class IdentityProvider(ABC):
    """Manages workload identity provisioning."""

    @abstractmethod
    def get_name(self) -> str:
        """
        Returns the provider name.

        Returns:
            str: Provider name (e.g., 'spire', 'serviceaccount')
        """
        pass

    @abstractmethod
    def get_current_identity(self) -> WorkloadIdentity:
        """
        Retrieves identity for the current workload.

        Returns:
            WorkloadIdentity: The current workload's identity

        Raises:
            TokenNotFoundError: If no identity token can be found
            InvalidTokenError: If the token is invalid
        """
        pass

    @abstractmethod
    def get_manifest_patches(self, component_name: str) -> Dict[str, Any]:
        """
        Returns Kubernetes manifest patches to inject identity into a workload.

        Args:
            component_name: Name of the component/workload

        Returns:
            Dict[str, Any]: Dictionary containing volumes and volumeMounts to inject
                           Format: {
                               "volumes": [...],
                               "volumeMounts": [...],
                               "serviceAccountName": "..." (optional)
                           }
        """
        pass
