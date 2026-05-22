#!/usr/bin/env python3
"""
Keycloak Session Lifetime E2E Tests

Verifies that the kagenti realm has extended session/token lifetimes
configured, preventing "Signature has expired" errors on long-running
dev clusters (fixes #1009).

Usage:
    pytest tests/e2e/common/test_keycloak_session_lifetimes.py -v

Fixtures:
    keycloak_token: Authenticates and returns Keycloak access token
"""

import os

import pytest
import requests

from kagenti.tests.conftest import _keycloak_ssl_verify


class TestKeycloakSessionLifetimes:
    """Verify Keycloak realm session lifetime settings."""

    @pytest.mark.requires_features(["keycloak"])
    def test_realm_session_lifetimes(self, keycloak_token):
        """Verify the kagenti realm has extended session lifetimes.

        Reads realm settings via the Keycloak admin API and asserts that
        ssoSessionIdleTimeout, ssoSessionMaxLifespan, and accessTokenLifespan
        have been set to values greater than Keycloak defaults.

        Keycloak defaults:
            ssoSessionIdleTimeout: 1800 (30 min)
            ssoSessionMaxLifespan: 36000 (10 hours)
            accessTokenLifespan: 300 (5 min)
        """
        keycloak_base_url = os.environ.get("KEYCLOAK_URL", "http://localhost:8081")
        realm = os.environ.get("KEYCLOAK_REALM", "kagenti")
        access_token = keycloak_token["access_token"]
        realm_url = f"{keycloak_base_url}/admin/realms/{realm}"

        response = requests.get(
            realm_url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
            verify=_keycloak_ssl_verify(),
        )
        assert response.status_code == 200, (
            f"Failed to read realm settings: {response.status_code} {response.text}"
        )

        realm_data = response.json()

        # Verify SSO Session Idle > Keycloak default of 1800s
        sso_idle = realm_data.get("ssoSessionIdleTimeout", 0)
        assert sso_idle > 1800, (
            f"ssoSessionIdleTimeout={sso_idle}s is not greater than "
            f"Keycloak default (1800s). Session lifetimes may not be configured."
        )

        # Verify SSO Session Max > Keycloak default of 36000s
        sso_max = realm_data.get("ssoSessionMaxLifespan", 0)
        assert sso_max > 36000, (
            f"ssoSessionMaxLifespan={sso_max}s is not greater than "
            f"Keycloak default (36000s). Session lifetimes may not be configured."
        )

        # Verify Access Token Lifespan > Keycloak default of 300s
        access_lifespan = realm_data.get("accessTokenLifespan", 0)
        assert access_lifespan > 300, (
            f"accessTokenLifespan={access_lifespan}s is not greater than "
            f"Keycloak default (300s). Session lifetimes may not be configured."
        )

        print(f"\n✓ Realm '{realm}' session lifetimes configured correctly:")
        print(f"  SSO Session Idle:    {sso_idle}s ({sso_idle // 86400}d)")
        print(f"  SSO Session Max:     {sso_max}s ({sso_max // 86400}d)")
        print(f"  Access Token:        {access_lifespan}s ({access_lifespan // 60}m)")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
