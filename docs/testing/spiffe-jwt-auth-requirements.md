# Complete Requirements Checklist for SPIFFE JWT Authentication with Keycloak

**Last Updated**: 2026-06-30
**Tested With**: Keycloak 26.5.2, SPIRE 1.x

---

## 1. Keycloak Requirements

### Version
* **Minimum**: Keycloak 26.4.0 or later
* **Tested**: Keycloak 26.5.2
* **Status**: SPIFFE support is a preview feature (expected to be fully supported in 26.5+)

### Feature Flags
* May need to enable preview features (implementation-dependent):
    * Start Keycloak with `--features=preview`, OR
    * Enable specific feature: `--features=federated-client-authentication,spiffe`
    * Check your deployment method (container args, config file, etc.)

### Management Interface (NEW - Required for K8s)
* Keycloak 26.5.2+ requires explicit management interface configuration for health probes:
    ```yaml
    args:
    - start
    - --import-realm
    - --health-enabled=true
    - --http-management-port=9000
    ```
* Without this, Kubernetes readiness probes will fail (port 9000 not exposed)

### Identity Provider Configuration

Create a SPIFFE Identity Provider with these exact settings:

```json
{
  "alias": "spire-spiffe",  // Can be any name, but must match client config
  "providerId": "spiffe",   // ✅ MUST be "spiffe", NOT "oidc"
  "enabled": true,
  "types": ["CLIENT_ASSERTION"],  // ✅ REQUIRED - marks IdP for client auth
  "config": {
    "trustDomain": "spiffe://localtest.me",  // ✅ Full SPIFFE URI format
    "bundleEndpoint": "https://oidc-discovery.localtest.me/keys",  // ✅ HTTPS required
    "issuerUrl": "https://oidc-discovery.localtest.me",  // ✅ SPIRE OIDC provider URL (HTTPS)
    "validateSignature": "true"
  }
}
```

**Critical points:**
* ❌ **NOT** `providerId: "oidc"` (uses OAuth2 validation)
* ❌ **NOT** `jwksUrl` field (that's for OIDC provider)
* ✅ **YES** `trustDomain` field (SPIFFE-specific)
* ✅ **YES** `bundleEndpoint` field (SPIFFE-specific)
* ✅ **YES** `issuerUrl` field (optional but recommended for clarity)
* ✅ **HTTPS required** - SPIRE OIDC Discovery Provider only supports HTTPS
* ✅ Bundle endpoint must be resolvable by Keycloak (DNS + TLS trust required)

**How Keycloak Uses These URLs:**
- `bundleEndpoint`: Fetched by Keycloak to get JWKS for signature verification (HTTPS connection)
- `issuerUrl`: Used for IdP identification (not for JWT `iss` claim validation)
- JWT's `iss` claim: **NOT used** for JWKS fetching (common misconception!)

### TLS Certificate Trust (CRITICAL - NEW)

**Problem**: SPIRE OIDC Discovery Provider uses HTTPS with certificates signed by SPIRE's internal CA. Keycloak's Java runtime must trust this CA to fetch JWKS keys.

**Solution**: Import SPIRE CA bundle into Java truststore using an init container:

#### Step 1: Extract SPIRE CA Bundle

```bash
# Get the actual SPIRE root CA certificates (NOT the certificate from spire-oidc-tls secret!)
kubectl exec -n zero-trust-workload-identity-manager spire-server-0 -c spire-server -- \
  /opt/spire/bin/spire-server bundle show > /tmp/spire-ca-bundle.pem

# Create ConfigMap
kubectl create configmap spire-ca-bundle -n keycloak \
  --from-file=spire-ca.pem=/tmp/spire-ca-bundle.pem
```

**Important Notes:**
- ✅ Use `spire-server bundle show` - this is the canonical source of SPIRE root CAs
- ❌ DO NOT use the certificate from `spire-oidc-tls` Kubernetes secret - that's a leaf certificate, not the CA
- ✅ The bundle contains **TWO root CA certificates** (SPIRE rotates CAs for security)
- ✅ Both CAs have matching Subject and Issuer fields (self-signed roots)

#### Step 2: Keycloak StatefulSet with Init Container

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: keycloak
  namespace: keycloak
spec:
  template:
    spec:
      securityContext:
        fsGroup: 1000
      initContainers:
      - name: import-spire-ca
        image: quay.io/keycloak/keycloak:26.5.2
        securityContext:
          runAsUser: 0  # ✅ Required - needs root to write to emptyDir
        command:
        - sh
        - -c
        - |
          set -e
          # Make truststore directory writable
          chmod 777 /truststore || true

          # Copy default Java cacerts to shared volume
          cp /etc/pki/ca-trust/extracted/java/cacerts /truststore/cacerts

          # Import SPIRE CA bundle into the truststore
          keytool -import -trustcacerts -noprompt \
            -alias spire-ca \
            -file /spire-ca/spire-ca.pem \
            -keystore /truststore/cacerts \
            -storepass changeit

          echo "SPIRE CA certificates imported successfully"
        volumeMounts:
        - name: spire-ca
          mountPath: /spire-ca
          readOnly: true
        - name: truststore
          mountPath: /truststore

      containers:
      - name: keycloak
        image: quay.io/keycloak/keycloak:26.5.2
        args:
        - start
        - --import-realm
        - --health-enabled=true
        - --http-management-port=9000
        env:
        - name: JAVA_OPTS_APPEND
          value: "-Djavax.net.ssl.trustStore=/truststore/cacerts -Djavax.net.ssl.trustStorePassword=changeit"
        # ... other env vars ...
        volumeMounts:
        - name: truststore
          mountPath: /truststore
          readOnly: true
        # ... other volume mounts ...

      volumes:
      - name: spire-ca
        configMap:
          name: spire-ca-bundle
      - name: truststore
        emptyDir: {}
      # ... other volumes ...
```

**Why This Is The Standard Approach:**
- This is how enterprises handle custom CAs in Java applications
- `keytool` and custom truststores are the official Java mechanism
- Same pattern used for corporate proxies, service meshes, internal APIs
- We're **adding** SPIRE's CA to the trust chain, **not disabling validation**
- ConfigMap + init container is the standard Kubernetes pattern

**What Would Be Wrong:**
- ❌ Disabling TLS validation (`-Djavax.net.ssl.trustAll=true`) - security nightmare
- ❌ Using HTTP instead of HTTPS - SPIRE OIDC provider doesn't support HTTP
- ❌ Patching Keycloak code - not maintainable

### Client Configuration

Configure the client (operator or agent) with these settings:

```json
{
  "clientId": "spiffe://localtest.me/ns/kagenti-system/sa/controller-manager",
  "enabled": true,
  "clientAuthenticatorType": "federated-jwt",  // ✅ Required
  "serviceAccountsEnabled": true,  // ✅ Required for client credentials grant
  "attributes": {
    "jwt.credential.issuer": "spire-spiffe",  // ✅ IdP ALIAS, not URL!
    "jwt.credential.sub": "spiffe://localtest.me/ns/kagenti-system/sa/controller-manager",  // ✅ Must match JWT sub claim
    "standard.token.exchange.enabled": "true"  // ✅ Recommended for token exchange
  }
}
```

**Critical points:**
* `jwt.credential.issuer` must be the IdP **alias** (e.g., `"spire-spiffe"`), **NOT a URL**
* `jwt.credential.sub` must exactly match the `sub` claim in the JWT-SVID
* `clientAuthenticatorType` must be `"federated-jwt"`, not `"client-secret"` or `"jwt"`
* After Keycloak issue #43394 fix (26.5.0+), the IdP is looked up by alias, not by validating the JWT `iss` claim

### Realm Configuration

* Realm issuer URL must be consistent and resolvable
* Check via: `GET /realms/{realm}/.well-known/openid-configuration`
* The `issuer` field value is what you need for JWT audience

Example:

```json
{
  "issuer": "http://keycloak.localtest.me:8080/realms/kagenti"
}
```

**Important**: This issuer URL is configured via Keycloak's `KC_HOSTNAME` environment variable and is used for audience validation.

---

## 2. SPIRE Configuration

### SPIRE OIDC Discovery Provider

Create ConfigMap with this configuration:

```json
{
  "set_key_use": true,  // ✅ REQUIRED for Keycloak SPIFFE provider
  "domains": [
    "spire-spiffe-oidc-discovery-provider",
    "spire-spiffe-oidc-discovery-provider.zero-trust-workload-identity-manager",
    "spire-spiffe-oidc-discovery-provider.zero-trust-workload-identity-manager.svc.cluster.local",
    "oidc-discovery.localtest.me"  // ✅ External hostname for HTTPS access
  ],
  "workload_api": {
    "socket_path": "/spiffe-workload-api/spire-agent.sock",
    "trust_domain": "localtest.me"
  }
}
```

**Critical points:**
* ✅ `set_key_use: true` is **REQUIRED** - adds `"use": "sig"` to JWKS keys
* Without this, Keycloak's SPIFFE provider cannot validate signatures properly
* ✅ **HTTPS is mandatory** - SPIRE OIDC Discovery Provider only supports HTTPS (port 8443)
* ❌ `allow_insecure_scheme: true` does NOT enable HTTP - it only allows HTTP in `domains` list
* ✅ Must include external hostname (e.g., `oidc-discovery.localtest.me`) for HTTPS access
* ✅ TLS certificates are automatically managed by SPIRE

### DNS Resolution for OIDC Discovery Endpoint

Since Keycloak needs to resolve the HTTPS endpoint (e.g., `https://oidc-discovery.localtest.me`), you need DNS resolution:

**Option A: CoreDNS Custom Host (Recommended for internal clusters)**

```yaml
# Add to CoreDNS ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns
  namespace: kube-system
data:
  Corefile: |
    .:53 {
        # ... existing config ...
        hosts {
            10.96.232.71 oidc-discovery.localtest.me
            fallthrough
        }
        # ... rest of config ...
    }
```

Where `10.96.232.71` is the ClusterIP of the SPIRE OIDC Discovery Provider service.

**Option B: ExternalName Service (Alternative)**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: oidc-discovery-localtest-me
  namespace: keycloak
spec:
  type: ExternalName
  externalName: spire-spiffe-oidc-discovery-provider.zero-trust-workload-identity-manager.svc.cluster.local
  ports:
  - port: 443
    targetPort: 8443
```

**Important**: The hostname in the `bundleEndpoint` URL must resolve to the SPIRE OIDC Discovery service from within the Keycloak pod.

### JWT-SVID TTL (Recommended)

Configure SPIRE server with appropriate JWT TTL:

```yaml
spire-server:
  controllerManager:
    identities:
      clusterSPIFFEIDs:
        default:
          jwtTTL: "5m"  # ✅ 5 minutes recommended for Keycloak
```

**Why**: Keycloak may reject JWTs older than 3-5 minutes. SPIRE refreshes tokens automatically (~2.5 min with 5min TTL).

### SPIRE jwt_issuer Configuration

The `jwt_issuer` setting in SPIRE server config should match your external hostname:

```yaml
spire-server:
  oidcDiscoveryProvider:
    config:
      jwt_issuer: "https://oidc-discovery.localtest.me"  # ✅ HTTPS with external hostname
```

**Key Insight**: Keycloak **does not use** the JWT's `iss` claim to fetch JWKS. It uses the configured `bundleEndpoint`. However, the JWT `iss` claim should still be accurate for logging and debugging purposes.

---

## 3. Client Application Requirements (Operator/Agent Code)

### JWT Assertion Type (CRITICAL!)

When making the client credentials grant request to Keycloak, you **MUST** use the correct assertion type:

```http
POST /realms/kagenti/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
&client_id=spiffe://localtest.me/ns/kagenti-system/sa/controller-manager
&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-spiffe
&client_assertion=<JWT-SVID>
```

**CRITICAL:**
* ✅ **MUST** use: `urn:ietf:params:oauth:client-assertion-type:jwt-spiffe`
* ❌ **NOT**: `urn:ietf:params:oauth:client-assertion-type:jwt-bearer`

**Why**: Keycloak's `SpiffeIdentityProvider` explicitly validates:
```java
validator.setExpectedClientAssertionType(SpiffeConstants.CLIENT_ASSERTION_TYPE);
// Where CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-spiffe"
```

Using `jwt-bearer` will result in immediate rejection with `invalid_client_credentials` error.

### JWT Audience Configuration (CRITICAL!)

This is the most critical and confusing part.

**The Problem:**
- Your application may use an **internal** Keycloak URL (e.g., `http://keycloak-service.keycloak.svc:8080`) for API calls
- But Keycloak expects JWT audience to match its **external** realm issuer (e.g., `http://keycloak.localtest.me:8080/realms/kagenti`)
- These URLs are different!

**The Solution:**

Use separate configuration values:

```yaml
# authbridge-config ConfigMap
KEYCLOAK_URL: "http://keycloak-service.keycloak.svc:8080"  # Internal service URL for API calls
KEYCLOAK_REALM: "kagenti"
EXPECTED_AUDIENCE: "http://keycloak.localtest.me:8080/realms/kagenti"  # External realm issuer for JWT audience
```

**Application Code Pattern:**

```go
// When fetching JWT-SVID from SPIRE
audience := config.ExpectedAudience
if audience == "" {
    // Fallback: construct from KEYCLOAK_URL (may not work if using internal URL!)
    audience = config.KeycloakURL + "/realms/" + config.Realm
}

jwtSVID, err := spireClient.FetchJWTSVID(ctx, audience)

// When calling Keycloak Admin API
adminAPIURL := config.KeycloakURL + "/admin/realms/" + config.Realm + "/clients"
```

**How to find the correct audience:**

```bash
curl http://keycloak-service.keycloak.svc:8080/realms/kagenti/.well-known/openid-configuration | jq -r .issuer
```

The value of the `issuer` field is your required audience.

**Alternative**: Dynamic discovery at startup:
```go
// Query .well-known/openid-configuration once at startup
wellKnown := fetchJSON(keycloakURL + "/realms/" + realm + "/.well-known/openid-configuration")
audience := wellKnown["issuer"]  // Use this for all JWT-SVID fetches
```

### JWT Claims Validation

The resulting JWT-SVID must contain:

```json
{
  "aud": ["http://keycloak.localtest.me:8080/realms/kagenti"],  // ✅ Realm issuer URL (external)
  "sub": "spiffe://localtest.me/ns/kagenti-system/sa/controller-manager",  // ✅ SPIFFE ID
  "iss": "https://oidc-discovery.localtest.me",  // ✅ SPIRE OIDC provider URL (HTTPS)
  "exp": 1781036549,  // ✅ Future timestamp
  "iat": 1781036249   // ✅ Issued-at timestamp
}
```

**Note**: No `jti` claim required (unlike standard OAuth2 client assertions)

---

## 4. Network/DNS Requirements

### Internal vs External URLs

You need to understand which component accesses which URL:

| Component | Accesses | Uses URL Type | Example |
|-----------|----------|---------------|---------|
| Workload (operator/agent) | Requests JWT-SVID from SPIRE | N/A (Unix socket) | `/spiffe-workload-api/spire-agent.sock` |
| Workload | Sends JWT to Keycloak | Either internal or external | `http://keycloak-service.keycloak.svc:8080` OR `http://keycloak.localtest.me:8080` |
| Keycloak | Fetches JWKS from SPIRE | HTTPS with resolvable hostname | `https://oidc-discovery.localtest.me/keys` |
| JWT audience claim | Must match realm issuer | External hostname (or whatever KC_HOSTNAME is set to) | `http://keycloak.localtest.me:8080/realms/kagenti` |

**Key insight**: Even if your workload talks to Keycloak via internal URLs, the JWT audience must match the public realm issuer configured in Keycloak's `KC_HOSTNAME`.

### DNS Resolution Options

**Option A: Use EXPECTED_AUDIENCE + CoreDNS (Recommended)**
- Configure external realm issuer URL in application config
- Add CoreDNS custom host entry for OIDC discovery endpoint
- Works on any platform (Kind, OpenShift, EKS, etc.)
- Less "magic", more explicit

**Option B: ExternalName Service (More Complex)**
- Create ExternalName service for OIDC discovery endpoint
- Allows using service name in `bundleEndpoint`
- But requires additional K8s resources

**Recommendation**: Use Option A (EXPECTED_AUDIENCE + CoreDNS) for production deployments.

---

## 5. Security Context (Kubernetes-specific)

If using spiffe-helper sidecar to write JWT-SVID to shared volume:

```yaml
securityContext:
  fsGroup: 1000  # ✅ Allows multiple containers to read JWT file

containers:
- name: spiffe-helper
  securityContext:
    runAsUser: 1000  # ✅ Must match fsGroup

- name: manager
  securityContext:
    runAsUser: 1000  # ✅ Must match to read JWT file
```

---

## 6. Bootstrap Job Requirements

The bootstrap job that sets up the operator client needs:

1. **RBAC permissions** to read secrets from Keycloak namespace

2. **Environment variables:**
    * `KEYCLOAK_URL`: Internal service URL (for Admin API calls)
    * `KEYCLOAK_REALM`: Realm name
    * `SPIFFE_IDP_ALIAS`: IdP alias (e.g., `spire-spiffe`)
    * `SPIFFE_TRUST_DOMAIN`: Without `spiffe://` prefix (e.g., `localtest.me`)
    * `SPIRE_OIDC_URL`: SPIRE OIDC discovery URL (HTTPS)
    * `EXPECTED_AUDIENCE`: External realm issuer URL (for JWT audience)
    * `OPERATOR_NAMESPACE`: Where operator runs
    * `OPERATOR_SERVICE_ACCOUNT`: ServiceAccount name

3. **Must run AFTER:**
    * SPIRE is deployed and OIDC provider is running
    * Keycloak is deployed and realm is created
    * SPIRE OIDC provider ConfigMap has `set_key_use: true`
    * SPIFFE IdP is created in Keycloak with correct configuration
    * **SPIRE CA bundle is imported into Keycloak's truststore** (required for HTTPS validation)

4. **Must use correct assertion type:**
    * When authenticating to create the operator client, the bootstrap job must also use `jwt-spiffe` assertion type

---

## 7. Common Pitfalls & Errors

| Error Message | Cause | Solution |
|---------------|-------|----------|
| `"invalid_client_credentials"` | Wrong assertion type (`jwt-bearer` instead of `jwt-spiffe`) | Use `urn:ietf:params:oauth:client-assertion-type:jwt-spiffe` |
| `"Invalid token audience"` | JWT audience doesn't match realm issuer | Use `EXPECTED_AUDIENCE` from config or query `.well-known/openid-configuration` |
| `"Issuer does not support client assertions"` | Using `providerId: "oidc"` | Change to `providerId: "spiffe"` |
| `"Invalid client credentials"` (generic) | `jwt.credential.issuer` is wrong | Use IdP alias (e.g., `"spire-spiffe"`), not URL |
| Signature validation fails | `set_key_use: false` or missing | Enable `set_key_use: true` in SPIRE OIDC config |
| **`"PKIX path building failed"`** (NEW) | SPIRE CA not in Java truststore | Import SPIRE CA bundle into Keycloak's truststore via init container |
| **`"certificate_unknown"` TLS error** (NEW) | SPIRE CA not trusted by Java | Same as above - import SPIRE CA bundle |
| Cannot fetch JWKS | DNS resolution failure or wrong URL | Use resolvable hostname in `bundleEndpoint`, add CoreDNS entry |
| **Keycloak readiness probe fails** (NEW) | Management port not exposed | Add `--health-enabled=true --http-management-port=9000` to Keycloak args |
| `"Invalid trust-domain"` | JWT `sub` doesn't start with `trustDomain + "/"` | Ensure `trustDomain` in IdP config matches JWT's SPIFFE ID prefix |
| `"Connection refused"` to OIDC endpoint | SPIRE OIDC provider not running or wrong port | SPIRE OIDC provider listens on port 8443 (HTTPS), ensure service is correct |

---

## 8. Validation Order (What Keycloak Checks)

Understanding the validation order helps debug failures:

1. **Assertion Type Check** → `jwt-spiffe` required
2. **IdP Lookup** → By `jwt.credential.issuer` alias
3. **Client Authenticator Type** → Must be `federated-jwt`
4. **Trust Domain** → JWT `sub` must start with `trustDomain + "/"`
5. **Audience** → JWT `aud` must match realm issuer
6. **TLS Connection** (NEW) → Keycloak connects to `bundleEndpoint` via HTTPS, validates TLS certificate
7. **Signature** → JWT signature valid against JWKS from `bundleEndpoint`
8. **Expiration** → JWT not expired (`exp` claim)
9. **Clock Skew** → `iat` and `exp` within allowed tolerance

**Tip**: Enable Keycloak debug logging to see which step fails:
```yaml
env:
  - name: KC_LOG_LEVEL
    value: "DEBUG,org.keycloak.broker:debug,org.keycloak.authentication:debug"
```

---

## 9. Quick Validation Checklist

Before testing end-to-end:

**Keycloak:**
- [ ] Keycloak version ≥ 26.4.0
- [ ] Preview features enabled: `--features=preview,spiffe`
- [ ] Management interface enabled: `--health-enabled=true --http-management-port=9000`
- [ ] **SPIRE CA bundle imported into Java truststore** (via init container)
- [ ] SPIFFE IdP created with `providerId: "spiffe"` (not `"oidc"`)
- [ ] IdP has `trustDomain` and `bundleEndpoint` (not `issuer`/`jwksUrl`)
- [ ] IdP has `types: ["CLIENT_ASSERTION"]`
- [ ] Bundle endpoint uses **HTTPS** with resolvable hostname
- [ ] Bundle endpoint DNS resolves from within Keycloak pod

**SPIRE:**
- [ ] SPIRE OIDC config has `set_key_use: true`
- [ ] JWT TTL configured (5 minutes recommended)
- [ ] OIDC discovery provider is running and accessible on port 8443 (HTTPS)
- [ ] External hostname (e.g., `oidc-discovery.localtest.me`) in `domains` list
- [ ] DNS resolution configured (CoreDNS or ExternalName service)

**Client Application:**
- [ ] Uses `jwt-spiffe` assertion type (NOT `jwt-bearer`)
- [ ] Uses `EXPECTED_AUDIENCE` for JWT-SVID audience
- [ ] `EXPECTED_AUDIENCE` matches Keycloak realm issuer exactly
- [ ] Client has `clientAuthenticatorType: "federated-jwt"`
- [ ] Client has `jwt.credential.issuer` = IdP alias (not URL)
- [ ] Client has `jwt.credential.sub` = expected SPIFFE ID
- [ ] Client has `serviceAccountsEnabled: true`

**Network:**
- [ ] Workloads can reach Keycloak (internal or external URL)
- [ ] Keycloak can resolve and reach SPIRE bundle endpoint (HTTPS with TLS validation)
- [ ] DNS resolves correctly for configured URLs

**Testing:**
- [ ] Bootstrap job completes successfully
- [ ] Operator/agent can fetch JWT-SVID from SPIRE
- [ ] JWT-SVID has correct `aud`, `sub`, `iss` claims
- [ ] Client credentials grant succeeds
- [ ] Access token obtained from Keycloak

---

## 10. Testing Commands

### Extract and Verify SPIRE CA Bundle (NEW)

```bash
# Extract SPIRE CA bundle (contains TWO root CAs)
kubectl exec -n zero-trust-workload-identity-manager spire-server-0 -c spire-server -- \
  /opt/spire/bin/spire-server bundle show > /tmp/spire-ca-bundle.pem

# Verify it contains certificates
openssl x509 -in /tmp/spire-ca-bundle.pem -text -noout | grep -E "Subject:|Issuer:"

# Count certificates in bundle (should be 2)
grep -c "BEGIN CERTIFICATE" /tmp/spire-ca-bundle.pem
```

### Verify SPIRE OIDC Provider (HTTPS)

```bash
# From within a pod in the cluster (with curl and openssl)
kubectl run test-oidc --rm -i --restart=Never --image=alpine/curl -- sh -c "
  apk add --no-cache openssl

  # Test HTTPS connectivity
  curl -v https://oidc-discovery.localtest.me/.well-known/openid-configuration

  # Check JWKS has 'use': 'sig'
  curl -s https://oidc-discovery.localtest.me/keys | grep -o '\"use\":\"sig\"'
"
```

### Verify Keycloak Truststore (NEW)

```bash
# Check if SPIRE CA is in Keycloak's truststore
kubectl exec -n keycloak keycloak-0 -- \
  keytool -list -keystore /truststore/cacerts -storepass changeit -alias spire-ca
```

### Verify Keycloak Realm Issuer

```bash
# Get the realm issuer (this is your required JWT audience)
curl -s http://keycloak.localtest.me:8080/realms/kagenti/.well-known/openid-configuration | jq -r '.issuer'
```

### Verify SPIFFE IdP in Keycloak

```bash
# Get admin token
TOKEN=$(kubectl -n keycloak get secret keycloak-initial-admin -o jsonpath='{.data.password}' | base64 -d | \
  xargs -I {} curl -s -X POST "http://keycloak.localtest.me:8080/realms/master/protocol/openid-connect/token" \
  -d "grant_type=password" -d "client_id=admin-cli" -d "username=admin" -d "password={}" | jq -r '.access_token')

# Get SPIFFE IdP config
curl -s "http://keycloak.localtest.me:8080/admin/realms/kagenti/identity-provider/instances/spire-spiffe" \
  -H "Authorization: Bearer $TOKEN" | jq '{alias, providerId, enabled, types, config}'
```

### Test Client Credentials Grant

```bash
# Fetch JWT-SVID (example with SPIRE agent API)
JWT_SVID=$(./spire-agent api fetch jwt \
  -audience "http://keycloak.localtest.me:8080/realms/kagenti" \
  -spiffeID "spiffe://localtest.me/ns/kagenti-system/sa/controller-manager")

# Test authentication
curl -X POST "http://keycloak.localtest.me:8080/realms/kagenti/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=spiffe://localtest.me/ns/kagenti-system/sa/controller-manager" \
  -d "client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-spiffe" \
  -d "client_assertion=$JWT_SVID"
```

### Check Operator Logs

```bash
# Watch for successful registration
kubectl logs -n kagenti-system deployment/kagenti-controller-manager -c manager -f | \
  grep -E "registered|SPIFFE|error"
```

### Debug TLS Issues (NEW)

```bash
# Test TLS connection from Keycloak pod to SPIRE OIDC endpoint
kubectl exec -n keycloak keycloak-0 -- sh -c "
  # Install openssl if needed
  microdnf install -y openssl || true

  # Test TLS handshake
  echo | openssl s_client -connect oidc-discovery.localtest.me:443 -showcerts 2>&1 | \
    grep -E 'Verify return code|subject=|issuer='
"
```

---

## 11. Reference Links

- **Keycloak SPIFFE Provider**: https://www.keycloak.org/docs/latest/server_admin/#_spiffe_provider
- **SPIFFE Spec**: https://github.com/spiffe/spiffe/blob/main/standards/SPIFFE.md
- **JWT-SVID Spec**: https://github.com/spiffe/spiffe/blob/main/standards/JWT-SVID.md
- **Keycloak Issue #43394**: Fixed in 26.5.0 - IdP lookup by alias instead of issuer validation
- **OAuth 2.0 JWT Client Assertion**: RFC 7523
- **Java Keytool**: https://docs.oracle.com/javase/8/docs/technotes/tools/unix/keytool.html

---

## 12. Summary of Key Findings (2026-06-30)

Based on extensive E2E testing with Keycloak 26.5.2 and SPIRE 1.x:

1. ✅ **HTTPS is mandatory** - SPIRE OIDC Discovery Provider only supports HTTPS (port 8443)
2. ✅ **TLS trust is critical** - Keycloak must trust SPIRE's CA to fetch JWKS keys
3. ✅ **Standard Java truststore import** - Use init container with `keytool` to import SPIRE CA bundle
4. ✅ **Extract CA from SPIRE server** - Use `spire-server bundle show`, NOT the `spire-oidc-tls` secret
5. ✅ **SPIRE CA bundle has TWO certificates** - SPIRE rotates root CAs for security
6. ✅ **Keycloak 26.5.2 health probes** - Require `--health-enabled=true` for management interface
7. ✅ **DNS resolution required** - External hostname must resolve to SPIRE OIDC service (CoreDNS entry)
8. ✅ **All authentication works end-to-end** - Operator → Keycloak → Agent credentials → Access tokens

**This configuration is production-ready and follows enterprise best practices.**

---

This comprehensive checklist captures all the requirements and pitfalls discovered through extensive testing and debugging!
