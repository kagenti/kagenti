#!/usr/bin/env python3
"""
setup_spiffe_idp.py

Sets up SPIFFE Identity Provider in Keycloak for JWT-SVID authentication.

This script:
1. Verifies SPIRE is running and accessible
2. Creates or updates the SPIFFE Identity Provider in Keycloak
3. Validates the JWKS endpoint has the required "use" field

Usage:
    python setup_spiffe_idp.py

Environment Variables:
    KEYCLOAK_BASE_URL: Keycloak server URL (default: http://keycloak-service.keycloak:8080)
    KEYCLOAK_REALM: Target realm name (default: kagenti)
    KEYCLOAK_NAMESPACE: Namespace containing Keycloak (default: keycloak)
    KEYCLOAK_ADMIN_SECRET_NAME: Secret name containing admin credentials (default: keycloak-initial-admin)
    KEYCLOAK_ADMIN_USERNAME_KEY: Key in Secret for username (default: username)
    KEYCLOAK_ADMIN_PASSWORD_KEY: Key in Secret for password (default: password)
    KEYCLOAK_TLS_VERIFY: Enable TLS certificate verification (default: true, set to "false" to disable)
    SPIFFE_TRUST_DOMAIN: SPIFFE trust domain (default: spiffe://localtest.me)
    SPIFFE_BUNDLE_ENDPOINT: JWKS URL (default: http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys)
    SPIFFE_IDP_ALIAS: Identity Provider alias (default: spire-spiffe)
    SPIFFE_TLS_VERIFY: Enable TLS verification for SPIRE endpoint (default: true, set to "false" to disable)
    SPIRE_NAMESPACE: SPIRE server namespace for validation (default: spire-server)
"""

import os
import sys
import time
import json
import base64
import logging
from typing import Optional, Tuple
import requests
from keycloak import KeycloakAdmin, KeycloakPostError, KeycloakGetError
from kubernetes import client, config as kube_config
from kubernetes.client.rest import ApiException

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration from environment
KEYCLOAK_BASE_URL = os.getenv(
    "KEYCLOAK_BASE_URL", "http://keycloak-service.keycloak:8080"
)
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "kagenti")
KEYCLOAK_NAMESPACE = os.getenv("KEYCLOAK_NAMESPACE", "keycloak")
KEYCLOAK_ADMIN_SECRET_NAME = os.getenv(
    "KEYCLOAK_ADMIN_SECRET_NAME", "keycloak-initial-admin"
)
KEYCLOAK_ADMIN_USERNAME_KEY = os.getenv("KEYCLOAK_ADMIN_USERNAME_KEY", "username")
KEYCLOAK_ADMIN_PASSWORD_KEY = os.getenv("KEYCLOAK_ADMIN_PASSWORD_KEY", "password")
SPIFFE_TRUST_DOMAIN = os.getenv("SPIFFE_TRUST_DOMAIN", "spiffe://localtest.me")
SPIFFE_BUNDLE_ENDPOINT = os.getenv(
    "SPIFFE_BUNDLE_ENDPOINT",
    "http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys",
)
SPIFFE_IDP_ALIAS = os.getenv("SPIFFE_IDP_ALIAS", "spire-spiffe")
SPIRE_NAMESPACE = os.getenv("SPIRE_NAMESPACE", "spire-server")
# TLS verification - defaults to True (secure), set KEYCLOAK_TLS_VERIFY=false to disable
KEYCLOAK_TLS_VERIFY = os.getenv("KEYCLOAK_TLS_VERIFY", "true").lower() != "false"
SPIFFE_TLS_VERIFY = os.getenv("SPIFFE_TLS_VERIFY", "true").lower() != "false"


def read_keycloak_credentials() -> Tuple[str, str]:
    """
    Read Keycloak admin credentials from Kubernetes Secret.

    Returns:
        Tuple of (username, password)
    """
    try:
        # Load Kubernetes config (in-cluster or kubeconfig)
        try:
            kube_config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except kube_config.ConfigException:
            kube_config.load_kube_config()
            logger.info("Loaded kubeconfig")

        v1 = client.CoreV1Api()

        logger.info(
            f"Reading credentials from Secret in namespace: {KEYCLOAK_NAMESPACE}"
        )

        secret = v1.read_namespaced_secret(
            name=KEYCLOAK_ADMIN_SECRET_NAME, namespace=KEYCLOAK_NAMESPACE
        )

        # Extract base64-encoded values from Secret (still encoded at this point)
        username_b64 = secret.data.get(KEYCLOAK_ADMIN_USERNAME_KEY)
        password_b64 = secret.data.get(KEYCLOAK_ADMIN_PASSWORD_KEY)

        if not username_b64 or not password_b64:
            raise ValueError(
                f"Secret {KEYCLOAK_ADMIN_SECRET_NAME} missing required keys: "
                f"{KEYCLOAK_ADMIN_USERNAME_KEY}, {KEYCLOAK_ADMIN_PASSWORD_KEY}"
            )

        # Decode base64 strings to plaintext
        username = base64.b64decode(username_b64).decode("utf-8")
        password = base64.b64decode(password_b64).decode("utf-8")

        logger.info(f"✅ Successfully read credentials from Secret")
        return username, password

    except ApiException as e:
        logger.error(f"❌ Failed to read Secret: {e}")
        logger.error(f"Ensure Secret exists in namespace: {KEYCLOAK_NAMESPACE}")
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error reading credentials: {e}")
        raise


def wait_for_spire(max_attempts: int = 30, delay_seconds: int = 10) -> bool:
    """
    Wait for SPIRE OIDC discovery provider to be accessible.

    Returns:
        True if SPIRE is accessible, False otherwise
    """
    logger.info("=" * 60)
    logger.info("Waiting for SPIRE OIDC Discovery Provider")
    logger.info("=" * 60)
    logger.info(f"Checking: {SPIFFE_BUNDLE_ENDPOINT}")
    logger.info(f"Max attempts: {max_attempts} (delay: {delay_seconds}s)")

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(
                f"Attempt {attempt}/{max_attempts}: Checking SPIRE availability..."
            )
            response = requests.get(
                SPIFFE_BUNDLE_ENDPOINT, timeout=5, verify=SPIFFE_TLS_VERIFY
            )

            if response.status_code == 200:
                jwks = response.json()
                keys = jwks.get("keys", [])

                if not keys:
                    logger.warning(f"  JWKS endpoint accessible but has no keys")
                    time.sleep(delay_seconds)
                    continue

                # Check if keys have "use" field (required for Keycloak)
                # Retry instead of failing immediately — the OIDC provider may
                # still be reloading after a ConfigMap patch + rollout restart.
                first_key = keys[0]
                if "use" not in first_key:
                    logger.warning(
                        f"  JWKS keys missing 'use' field (attempt {attempt}/{max_attempts})"
                    )
                    logger.warning(
                        f"  SPIRE OIDC provider may still be reloading config"
                    )
                    if attempt < max_attempts:
                        logger.info(f"  Retrying in {delay_seconds} seconds...")
                        time.sleep(delay_seconds)
                        continue
                    logger.error(
                        f"  ❌ JWKS keys still missing 'use' field after {max_attempts} attempts"
                    )
                    logger.error(f"  Ensure SPIRE is configured with set_key_use: true")
                    return False

                logger.info(f"  ✅ SPIRE OIDC Discovery Provider is ready")
                logger.info(f"  Found {len(keys)} key(s) with 'use' field")
                return True

        except requests.exceptions.RequestException as e:
            logger.warning(f"  Attempt {attempt} failed: {e}")
            if attempt < max_attempts:
                logger.info(f"  Retrying in {delay_seconds} seconds...")
                time.sleep(delay_seconds)

    logger.error(
        f"❌ SPIRE OIDC Discovery Provider not accessible after {max_attempts} attempts"
    )
    logger.error(
        f"Ensure SPIRE is installed and running in namespace '{SPIRE_NAMESPACE}'"
    )
    return False


def get_or_create_realm(keycloak_admin: KeycloakAdmin, realm_name: str) -> bool:
    """
    Create realm if it doesn't exist.

    Returns:
        True if realm exists or was created, False on error
    """
    try:
        realms = keycloak_admin.get_realms()
        if any(r["realm"] == realm_name for r in realms):
            logger.info(f"Realm '{realm_name}' already exists")
            return True
    except Exception as e:
        logger.warning(f"Could not list realms: {e}. Attempting create anyway.")

    try:
        keycloak_admin.create_realm(payload={"realm": realm_name, "enabled": True})
        logger.info(f"Created realm '{realm_name}'")
        return True
    except KeycloakPostError as e:
        if e.response_code == 409:
            logger.info(f"Realm '{realm_name}' already exists (409)")
            return True
        logger.error(f"Failed to create realm: {e}")
        return False


def ensure_spiffe_idp(
    kc: KeycloakAdmin, alias: str, trust_domain: str, bundle_endpoint: str
) -> bool:
    """
    Create or update a SPIFFE Identity Provider.

    Returns:
        True if IdP was created/updated, False on error
    """
    logger.info("=" * 60)
    logger.info("Setting up SPIFFE Identity Provider")
    logger.info("=" * 60)

    idp_payload = {
        "alias": alias,
        "providerId": "spiffe",  # Must be "spiffe", not "oidc"!
        "enabled": True,
        "config": {
            "trustDomain": trust_domain,
            "bundleEndpoint": bundle_endpoint,
            "validateSignature": "true",
        },
    }

    logger.info(f"Alias: {alias}")
    logger.info(f"Provider Type: spiffe")
    logger.info(f"Trust Domain: {trust_domain}")
    logger.info(f"Bundle Endpoint: {bundle_endpoint}")

    try:
        idps = kc.get_idps()
        existing_idp = next((p for p in idps if p.get("alias") == alias), None)

        if existing_idp:
            # Check if configuration needs updating
            existing_trust_domain = existing_idp.get("config", {}).get("trustDomain")
            existing_bundle_endpoint = existing_idp.get("config", {}).get(
                "bundleEndpoint"
            )

            if (
                existing_trust_domain == trust_domain
                and existing_bundle_endpoint == bundle_endpoint
            ):
                logger.info(
                    f"✅ SPIFFE Identity Provider '{alias}' already exists with correct configuration"
                )
                return True
            else:
                logger.info(f"Updating SPIFFE Identity Provider '{alias}':")
                if existing_trust_domain != trust_domain:
                    logger.info(
                        f"  Trust Domain: {existing_trust_domain} → {trust_domain}"
                    )
                if existing_bundle_endpoint != bundle_endpoint:
                    logger.info(
                        f"  Bundle Endpoint: {existing_bundle_endpoint} → {bundle_endpoint}"
                    )
                kc.update_idp(alias, idp_payload)
                logger.info(f"✅ SPIFFE Identity Provider '{alias}' updated")
                return True
    except KeycloakGetError as e:
        logger.warning(f"Could not list IdPs: {e}. Attempting to create.")

    try:
        kc.create_idp(idp_payload)
        logger.info(f"✅ Created SPIFFE Identity Provider '{alias}'")
        return True
    except KeycloakPostError as e:
        if e.response_code == 409:
            logger.info(f"Identity Provider '{alias}' already exists (409)")
            # Try to update it
            try:
                kc.update_idp(alias, idp_payload)
                logger.info(f"✅ Updated SPIFFE Identity Provider '{alias}'")
                return True
            except Exception as update_err:
                logger.error(f"Could not update IdP: {update_err}")
                return False
        logger.error(f"Failed to create Identity Provider: {e}")
        return False


def main() -> int:
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("SPIFFE Identity Provider Setup for Keycloak")
    logger.info("=" * 60)
    logger.info(f"Keycloak: {KEYCLOAK_BASE_URL}")
    logger.info(f"Realm: {KEYCLOAK_REALM}")
    logger.info(f"Trust Domain: {SPIFFE_TRUST_DOMAIN}")
    logger.info(f"IdP Alias: {SPIFFE_IDP_ALIAS}")
    logger.info("")

    # Step 1: Wait for SPIRE to be ready
    if not wait_for_spire():
        logger.error("❌ Setup failed: SPIRE not accessible")
        return 1

    logger.info("")

    # Step 2: Read Keycloak credentials from Secret
    logger.info("=" * 60)
    logger.info("Reading Keycloak Credentials")
    logger.info("=" * 60)

    try:
        admin_username, admin_password = read_keycloak_credentials()
    except Exception as e:
        logger.error(f"❌ Setup failed: Could not read Keycloak credentials: {e}")
        return 1

    logger.info("")

    # Step 3: Connect to Keycloak
    logger.info("=" * 60)
    logger.info("Connecting to Keycloak")
    logger.info("=" * 60)

    try:
        master_admin = KeycloakAdmin(
            server_url=KEYCLOAK_BASE_URL,
            username=admin_username,
            password=admin_password,
            realm_name="master",
            user_realm_name="master",
            verify=KEYCLOAK_TLS_VERIFY,
        )
        logger.info("✅ Connected to Keycloak master realm")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Keycloak: {e}")
        logger.error(f"Ensure Keycloak is running at: {KEYCLOAK_BASE_URL}")
        return 1

    logger.info("")

    # Step 4: Create target realm if needed
    logger.info("=" * 60)
    logger.info(f"Ensuring Realm: {KEYCLOAK_REALM}")
    logger.info("=" * 60)

    if not get_or_create_realm(master_admin, KEYCLOAK_REALM):
        logger.error(
            f"❌ Setup failed: Could not create/access realm '{KEYCLOAK_REALM}'"
        )
        return 1

    logger.info("")

    # Step 5: Switch to target realm
    try:
        kc = KeycloakAdmin(
            server_url=KEYCLOAK_BASE_URL,
            username=admin_username,
            password=admin_password,
            realm_name=KEYCLOAK_REALM,
            user_realm_name="master",
            verify=KEYCLOAK_TLS_VERIFY,
        )
        logger.info(f"✅ Switched to realm: {KEYCLOAK_REALM}")
    except Exception as e:
        logger.error(f"❌ Failed to switch to realm '{KEYCLOAK_REALM}': {e}")
        return 1

    logger.info("")

    # Step 6: Create SPIFFE Identity Provider
    if not ensure_spiffe_idp(
        kc, SPIFFE_IDP_ALIAS, SPIFFE_TRUST_DOMAIN, SPIFFE_BUNDLE_ENDPOINT
    ):
        logger.error("❌ Setup failed: Could not create SPIFFE Identity Provider")
        return 1

    logger.info("")
    logger.info("=" * 60)
    logger.info("✅ SPIFFE Identity Provider Setup Complete")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Next steps:")
    logger.info(f"1. Set authBridge.clientAuthType: 'federated-jwt' in values.yaml")
    logger.info(
        f"2. Deploy agents - they will automatically use JWT-SVID authentication"
    )
    logger.info("")
    logger.info("Verification:")
    logger.info(f"  Keycloak UI → {KEYCLOAK_REALM} realm → Identity Providers")
    logger.info(f"  Should see: {SPIFFE_IDP_ALIAS} (Type: SPIFFE)")
    logger.info("")

    return 0


if __name__ == "__main__":
    sys.exit(main())
