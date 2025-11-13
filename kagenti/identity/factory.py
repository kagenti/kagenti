"""
kagenti.identity.factory

Factory for creating identity providers.
"""

import os
from typing import Optional

from .provider import IdentityProvider
from .spire_provider import SPIREProvider
from .serviceaccount_provider import ServiceAccountProvider
from .exceptions import ProviderNotFoundError


def get_identity_provider(
    provider_name: Optional[str] = None,
    spire_token_path: str = "/opt/jwt_svid.token",
    sa_token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token",
) -> IdentityProvider:
    """
    Get an identity provider instance using explicit configuration.

    Args:
        provider_name: Explicit provider name ("spire" or "serviceaccount")
        spire_token_path: Path to SPIRE JWT token file
        sa_token_path: Path to ServiceAccount token file

    Returns:
        IdentityProvider instance

    Raises:
        ProviderNotFoundError: If provider is not specified or invalid
    """
    # Get provider name from parameter or environment variable
    if provider_name is None:
        provider_name = os.environ.get("KAGENTI_IDENTITY_PROVIDER")

    if not provider_name:
        raise ProviderNotFoundError(
            "Identity provider must be explicitly specified. "
            "Set KAGENTI_IDENTITY_PROVIDER environment variable to 'spire' or 'serviceaccount'."
        )

    provider_name = provider_name.lower().strip()

    # Explicit provider selection
    if provider_name == "spire":
        if not os.path.exists(spire_token_path):
            raise ProviderNotFoundError(
                f"SPIRE provider requested but token not found at {spire_token_path}. "
                "Ensure SPIRE is configured and the token is available."
            )
        return SPIREProvider(token_path=spire_token_path)

    if provider_name == "serviceaccount":
        if not os.path.exists(sa_token_path):
            raise ProviderNotFoundError(
                f"ServiceAccount provider requested but token not found at {sa_token_path}. "
                "Ensure the pod has a ServiceAccount configured."
            )
        return ServiceAccountProvider(token_path=sa_token_path)

    # Invalid provider name
    raise ProviderNotFoundError(
        f"Invalid identity provider name: '{provider_name}'. "
        "Valid options are: 'spire', 'serviceaccount'"
    )
