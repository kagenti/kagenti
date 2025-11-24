"""
kagenti.identity

Workload identity abstraction package for Kagenti.

This package provides a pluggable interface for workload identity providers,
supporting SPIRE/SPIFFE and Kubernetes ServiceAccounts.
"""

from .provider import WorkloadIdentity, IdentityProvider
from .spire_provider import SPIREProvider, SPIREIdentity
from .serviceaccount_provider import ServiceAccountProvider, ServiceAccountIdentity
from .factory import get_identity_provider
from .exceptions import (
    IdentityProviderError,
    TokenNotFoundError,
    InvalidTokenError,
    ProviderNotFoundError,
)

__all__ = [
    # Abstract classes
    "WorkloadIdentity",
    "IdentityProvider",
    # SPIRE implementation
    "SPIREProvider",
    "SPIREIdentity",
    # ServiceAccount implementation
    "ServiceAccountProvider",
    "ServiceAccountIdentity",
    # Factory function
    "get_identity_provider",
    # Exceptions
    "IdentityProviderError",
    "TokenNotFoundError",
    "InvalidTokenError",
    "ProviderNotFoundError",
]

__version__ = "0.1.0"
