# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Application configuration using Pydantic Settings.
"""

import re
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application settings
    debug: bool = False
    domain_name: str = "localtest.me"

    @property
    def is_running_in_cluster(self) -> bool:
        """Check if the backend is running inside a Kubernetes cluster."""
        import os

        return os.getenv("KUBERNETES_SERVICE_HOST") is not None

    # CORS settings
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
        "http://kagenti-ui.localtest.me:8080",
    ]

    # Kubernetes CRD settings
    crd_group: str = "agent.kagenti.dev"
    crd_version: str = "v1alpha1"
    agents_plural: str = "agents"
    agentbuilds_plural: str = "agentbuilds"

    # ToolHive CRD settings
    toolhive_crd_group: str = "toolhive.stacklok.dev"
    toolhive_crd_version: str = "v1alpha1"
    toolhive_mcp_plural: str = "mcpservers"

    # Shipwright build settings
    use_shipwright_builds: bool = True  # Use Shipwright instead of AgentBuild/Tekton
    shipwright_default_strategy: str = "buildah-insecure-push"  # Default for dev
    shipwright_default_timeout: str = "15m"

    # Migration settings (Phase 4: Agent CRD to Deployment migration)
    # When True, list_agents will also include legacy Agent CRDs that haven't been migrated
    enable_legacy_agent_crd: bool = True  # Set to False after full migration

    # Label settings
    kagenti_label_prefix: str = "kagenti.io/"
    enabled_namespace_label_key: str = "kagenti-enabled"
    enabled_namespace_label_value: str = "true"

    # External service URLs (read from ConfigMap via environment variables)
    traces_dashboard_url: str = ""
    network_dashboard_url: str = ""
    mcp_inspector_url: str = ""
    mcp_proxy_full_address: str = ""
    keycloak_console_url: str = ""

    # Authentication settings - from kagenti-ui-oauth-secret
    enable_auth: bool = False  # Set to True to enable Keycloak auth
    # AUTH_ENDPOINT format: http://keycloak.localtest.me:8080/realms/master/protocol/openid-connect/auth
    auth_endpoint: Optional[str] = None
    # REDIRECT_URI format: http://kagenti-ui.localtest.me:8080/oauth2/callback
    redirect_uri: Optional[str] = None
    # CLIENT_ID from the secret
    client_id: str = "kagenti-ui"

    # Legacy direct config (fallback if AUTH_ENDPOINT not provided)
    keycloak_url: str = ""
    keycloak_realm: str = "master"
    keycloak_client_id: str = "kagenti-ui"

    @property
    def effective_keycloak_url(self) -> str:
        """
        Extract Keycloak base URL from AUTH_ENDPOINT or use direct config.
        AUTH_ENDPOINT format: http://keycloak.localtest.me:8080/realms/master/protocol/openid-connect/auth
        Returns: http://keycloak.localtest.me:8080
        """
        if self.auth_endpoint:
            # Parse AUTH_ENDPOINT to extract base URL
            # Pattern: {base_url}/realms/{realm}/protocol/openid-connect/auth
            match = re.match(r"(https?://[^/]+)/realms/", self.auth_endpoint)
            if match:
                return match.group(1)
        # Fallback to direct config or default
        if self.keycloak_url:
            return self.keycloak_url
        return f"http://keycloak.{self.domain_name}:8080"

    @property
    def effective_keycloak_realm(self) -> str:
        """
        Extract realm from AUTH_ENDPOINT or use direct config.
        AUTH_ENDPOINT format: http://keycloak.localtest.me:8080/realms/master/protocol/openid-connect/auth
        Returns: master
        """
        if self.auth_endpoint:
            # Pattern: /realms/{realm}/protocol/
            match = re.search(r"/realms/([^/]+)/protocol/", self.auth_endpoint)
            if match:
                return match.group(1)
        return self.keycloak_realm

    @property
    def effective_client_id(self) -> str:
        """Get client ID from secret (CLIENT_ID) or fallback to direct config."""
        return self.client_id if self.client_id else self.keycloak_client_id

    @property
    def effective_redirect_uri(self) -> Optional[str]:
        """Get redirect URI for frontend Keycloak config."""
        return self.redirect_uri

    @property
    def kagenti_type_label(self) -> str:
        return f"{self.kagenti_label_prefix}type"

    @property
    def kagenti_protocol_label(self) -> str:
        return f"{self.kagenti_label_prefix}protocol"

    @property
    def kagenti_framework_label(self) -> str:
        return f"{self.kagenti_label_prefix}framework"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
