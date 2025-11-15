# Agent OAuth Secret 

This tool automates the setup of Keycloak realms, users, and OAuth clients for the Kagenti platform. It creates or updates Keycloak client secrets in multiple Kubernetes namespaces for agent authentication.

## Features

- **Automatic Keycloak realm and client provisioning**
- **Credential management** via environment variables or Kubernetes secrets
- **SSL/TLS certificate handling** with fallback to system CA bundle
- **In-cluster and off-cluster detection** for Kubernetes configuration
- **Secret distribution** across multiple agent namespaces

## Usage

### Running the tool

```bash
# Run directly
python kagenti/auth/agent-oauth-secret/agent_oauth_secret.py
```

### Prerequisites

- Python 3.8+
- Required packages: `typer`, `python-keycloak`, `kubernetes`
- Access to a Kubernetes cluster (via kubeconfig or in-cluster service account)
- Running Keycloak instance

## Environment Variables

### Required

- **`AGENT_NAMESPACES`** - Comma-separated list of Kubernetes namespaces where the client secret will be created/updated
  - Example: `"agent-ns-1,agent-ns-2,demo-agent"`

### Keycloak Connection (with defaults)

- **`KEYCLOAK_BASE_URL`** - Keycloak server URL
  - Default: `"http://keycloak.localtest.me:8080"`
  
- **`KEYCLOAK_DEMO_REALM`** - Name of the realm to create/use
  - Default: `"demo"`

- **`KAGENTI_KEYCLOAK_CLIENT_NAME`** - OAuth client name to create
  - Default: `"kagenti-keycloak-client"`

### Keycloak Admin Credentials

The tool supports **two methods** for providing Keycloak admin credentials:

#### Method 1: Direct environment variables (simple, for local development)

- **`KEYCLOAK_ADMIN_USERNAME`** - Admin username
  - Default: `"admin"`
  
- **`KEYCLOAK_ADMIN_PASSWORD`** - Admin password
  - Default: `"admin"`

#### Method 2: Kubernetes secret (recommended for production/CI)

If `KEYCLOAK_ADMIN_USERNAME` and `KEYCLOAK_ADMIN_PASSWORD` are not provided, the tool will attempt to read credentials from a Kubernetes secret:

- **`KEYCLOAK_NAMESPACE`** - Namespace containing the Keycloak admin secret
  - Default: `"keycloak"`

- **`KEYCLOAK_ADMIN_SECRET_NAME`** - Name of the secret containing admin credentials
  - Default: `"keycloak-initial-admin"`

- **`KEYCLOAK_ADMIN_USERNAME_KEY`** - Key in the secret for the username
  - Default: `"username"`

- **`KEYCLOAK_ADMIN_PASSWORD_KEY`** - Key in the secret for the password
  - Default: `"password"`

### SSL/TLS Configuration

- **`SSL_CERT_FILE`** - Path to custom CA certificate bundle for HTTPS connections to Keycloak
  - Optional. If not set or file doesn't exist, the system's default CA bundle will be used
  - Useful for self-signed certificates or internal CAs

### Test User Configuration (Optional)

These environment variables control the creation of a test user in the Keycloak realm. This is useful for development, testing, or CI environments.

- **`CREATE_KEYCLOAK_TEST_USER`** - If set to `"true"`, the tool will create a test user in the Keycloak realm.
  - Default: true (test user is created)

- **`KEYCLOAK_TEST_USER_NAME`** - Username for the test user.
  - Default: `"test-user"`

- **`KEYCLOAK_TEST_USER_PASSWORD`** - Password for the test user.
  - Default: Not set (required if CREATE_KEYCLOAK_TEST_USER is true)
## Configuration Examples

### Example 1: Local development with defaults

```bash
# Minimal configuration - uses all defaults
export AGENT_NAMESPACES="demo-agent,langgraph-agent"

# Run the script directly by path (directory name contains a hyphen)
python kagenti/auth/agent-oauth-secret/agent_oauth_secret.py
```

### Example 2: Custom Keycloak instance with explicit credentials

```bash
# Keycloak connection
export KEYCLOAK_BASE_URL="https://keycloak.example.com"
export KEYCLOAK_ADMIN_USERNAME="admin"
export KEYCLOAK_ADMIN_PASSWORD="secure-password"
export KEYCLOAK_DEMO_REALM="production"

# Client configuration
export KAGENTI_KEYCLOAK_CLIENT_NAME="kagenti-prod-client"

# Target namespaces
export AGENT_NAMESPACES="prod-agent-1,prod-agent-2"

# Run the script directly by path (directory name contains a hyphen)
python kagenti/auth/agent-oauth-secret/agent_oauth_secret.py
```

### Example 3: Production with secret-based credentials and custom CA

```bash
# Read credentials from Kubernetes secret in 'auth' namespace
export KEYCLOAK_NAMESPACE="auth"
export KEYCLOAK_ADMIN_SECRET_NAME="keycloak-admin-creds"

# Connection with custom CA
export KEYCLOAK_BASE_URL="https://keycloak.internal.company.com"
export SSL_CERT_FILE="/etc/ssl/certs/company-ca.crt"

# Target namespaces
export AGENT_NAMESPACES="agent-prod,agent-staging"

python kagenti/auth/agent-oauth-secret/agent_oauth_secret.py
```

### Example 4: In-cluster job (Kubernetes Job/CronJob)

When running as a Kubernetes Job, the tool automatically detects in-cluster mode:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: keycloak-setup
  namespace: kagenti-system
spec:
  template:
    spec:
      serviceAccountName: keycloak-setup-sa
      containers:
      - name: setup
        image: kagenti/agent-oauth-secret:latest
        env:
        - name: AGENT_NAMESPACES
          value: "team1,team2"
        - name: KEYCLOAK_BASE_URL
          value: "http://keycloak.keycloak.svc.cluster.local:8080"
        - name: KEYCLOAK_NAMESPACE
          value: "keycloak"
        - name: SSL_CERT_FILE
          value: "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
      restartPolicy: OnFailure
```

## What the Tool Does

1. **Connects to Kubernetes**
   - Detects in-cluster vs off-cluster environment
   - Loads appropriate kubeconfig

2. **Reads Keycloak credentials**
   - From environment variables (if provided)
   - OR from Kubernetes secret (fallback)

3. **Connects to Keycloak**
   - Uses configured SSL certificate if provided
   - Polls with retry logic (120s timeout, 5s intervals)

4. **Provisions Keycloak resources**
   - Creates realm (if it doesn't exist)
   - Creates test user: `test-user` (only if `KEYCLOAK_TEST_USER_PASSWORD` environment variable is set; password is taken from this variable)
   - Creates/retrieves OAuth client with SPIFFE ID format
   - Retrieves client secret

5. **Distributes secrets to namespaces**
   - For each namespace in `AGENT_NAMESPACES`:
     - Creates secret `kagenti-keycloak-client-secret` if it doesn't exist
     - Patches existing secret with new client secret value
   - Uses `stringData` field (no manual base64 encoding required)

## Created Kubernetes Secret

The tool creates/updates a secret in each target namespace with the following structure:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kagenti-keycloak-client-secret
type: Opaque
stringData:
  client-secret: "<keycloak-client-secret-value>"
```

## Client Configuration

The OAuth client created in Keycloak has the following properties:

- **Client ID format**: `spiffe://localtest.me/sa/{client-name}`
- **Standard flow enabled**: Yes (Authorization Code flow)
- **Direct access grants enabled**: Yes (Resource Owner Password Credentials)
- **Full scope allowed**: Yes
- **Enabled**: Yes

## Error Handling

The tool provides clear error messages for common issues:

- **Missing `AGENT_NAMESPACES`**: Exits silently (no work to do)
- **Kubernetes connection failure**: Displays error and exits with code 1
- **Keycloak connection timeout**: Fails after 120 seconds with retry logs
- **Secret read/write errors**: Shows detailed error messages
- **SSL certificate issues**: Falls back to system CA bundle with warning

## Troubleshooting

### Connection to Keycloak fails

- Verify `KEYCLOAK_BASE_URL` is correct and Keycloak is running
- Check network connectivity
- If using HTTPS with self-signed cert, ensure `SSL_CERT_FILE` points to valid CA bundle

### Cannot read admin credentials from secret

- Verify the secret exists: `kubectl get secret <secret-name> -n <namespace>`
- Check secret has the expected keys: `kubectl get secret <secret-name> -n <namespace> -o yaml`
- Ensure the service account has permission to read secrets in that namespace

### Secret not created in target namespace

- Verify namespace exists: `kubectl get namespace <namespace>`
- Check RBAC permissions for the service account
- Review logs for specific API errors

### In-cluster mode not detected

- Verify `KUBERNETES_SERVICE_HOST` environment variable is set
- Check service account token is mounted at `/var/run/secrets/kubernetes.io/serviceaccount/`

## Development

### Running locally

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install typer python-keycloak kubernetes

# Set environment variables
export AGENT_NAMESPACES="test-ns"
export KEYCLOAK_BASE_URL="http://localhost:8080"

# Run the tool
# Run the script directly by path (directory name contains a hyphen)
python kagenti/auth/agent-oauth-secret/agent_oauth_secret.py
```

### Running tests

```bash
pytest kagenti/auth/agent-oauth-secret/
```

## Related Tools

- **`ui-oauth-secret/auth_secret.py`** - Similar tool for UI OAuth configuration with additional OpenShift route support
- **Kagenti Installer** - Uses this tool as part of the platform installation process

## License

Apache License 2.0 - See LICENSE file for details.
