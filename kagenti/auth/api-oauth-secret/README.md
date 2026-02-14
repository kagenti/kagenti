# API OAuth Secret Job

Kubernetes Job that provisions backend API authentication in Keycloak:

1. **Creates RBAC realm roles** (`kagenti-viewer`, `kagenti-operator`, `kagenti-admin`) used by the backend API for endpoint authorization
2. **Assigns `kagenti-admin`** to the Keycloak admin user
3. **Registers `kagenti-api` confidential client** for programmatic API access via Client Credentials Grant
4. **Creates a K8s secret** (`kagenti-api-oauth-secret`) with the client credentials

## Related

- `kagenti/auth/agent-oauth-secret/` — Sets up Keycloak realm, clients, and test users for **agent-to-agent** and **agent-to-tool** authentication
- This job focuses on **backend API** authentication (UI and external clients)
