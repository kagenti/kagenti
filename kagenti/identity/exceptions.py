"""
kagenti.identity.exceptions

Custom exceptions for the identity package.
"""


class IdentityProviderError(Exception):
    """Base exception for identity provider errors."""

    pass


class TokenNotFoundError(IdentityProviderError):
    """Raised when an identity token cannot be found."""

    pass


class InvalidTokenError(IdentityProviderError):
    """Raised when an identity token is invalid or cannot be parsed."""

    pass


class ProviderNotFoundError(IdentityProviderError):
    """Raised when no suitable identity provider can be found."""

    pass
