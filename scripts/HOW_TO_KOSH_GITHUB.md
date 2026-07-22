# How to Enable GitHub Login for OpenShell (kosh)

This guide walks through enabling GitHub as an identity provider for an OpenShell tenant namespace, so users can authenticate to the gateway using their GitHub account.

**Goal:** A GitHub user can log into the OpenShell gateway using their GitHub identity.

**Approach:** Any GitHub user can authenticate, but only users added to the `openshell-users` Keycloak group get gateway access. No custom Keycloak image required.

---

## Variables

Set these for your cluster before following the steps:

```bash
CLUSTER_NAME="ykt1"                            # Cluster short name (for kubeconfig, app name)
CLUSTER_DOMAIN="apps.ykt1.hcp.res.ibm.com"    # OpenShift apps domain (example)
TENANT="aslom"                                 # Tenant namespace name
KEYCLOAK_NS="keycloak"                         # Keycloak namespace
REALM="openshell"                              # Keycloak realm
```

Derived URLs:
- **Keycloak**: `https://keycloak-${KEYCLOAK_NS}.${CLUSTER_DOMAIN}`
- **Gateway**: `https://openshell-${TENANT}.${CLUSTER_DOMAIN}`
- **Teleport setup**: `https://kagenti-teleport-setup-${TENANT}.${CLUSTER_DOMAIN}`

---

## Prerequisites

- `KUBECONFIG` pointing to a kubeconfig with cluster-admin access
- Keycloak running in `${KEYCLOAK_NS}` namespace
- OpenShell tenant deployed (e.g., `${TENANT}` namespace with gateway running)
- A GitHub account

---

## Step 1: Create a GitHub OAuth App

1. Go to <https://github.com/settings/developers>
2. Click **OAuth Apps** > **New OAuth App**
3. Fill in:

   | Field | Value |
   |-------|-------|
   | Application name | `kagenti-openshell-${CLUSTER_NAME}` |
   | Homepage URL | `https://keycloak-${KEYCLOAK_NS}.${CLUSTER_DOMAIN}` |
   | Authorization callback URL | `https://keycloak-${KEYCLOAK_NS}.${CLUSTER_DOMAIN}/realms/openshell/broker/github/endpoint` |

   > The callback URL format is: `https://<keycloak-host>/realms/<realm>/broker/<idp-alias>/endpoint`

4. Click **Register application**
5. Note the **Client ID** (e.g., `Ov23liXXXXXXXXXX`)
6. Click **Generate a new client secret** — copy and save it securely
7. In the OAuth App settings, check **Enable Device Flow** (required for CLI-based login without browser redirect)

### Transferring ownership later

The OAuth App can be created under your personal account initially. To transfer to an organization later:
1. Go to the OAuth App settings
2. Click **Transfer ownership**
3. Select the target org (e.g., `kagenti` or `IBM`)
4. Update the callback URL if the Keycloak hostname changes

---

## Step 2: Configure Keycloak — Add GitHub Identity Provider

### 2a. Log into Keycloak Admin Console

Open: <https://keycloak-${KEYCLOAK_NS}.${CLUSTER_DOMAIN}/admin>

Use the Keycloak admin credentials (stored in the `keycloak-initial-admin` secret in the `keycloak` namespace):

```bash
KUBECONFIG=.kube/config-${CLUSTER_NAME} kubectl get secret keycloak-initial-admin -n keycloak \
  -o jsonpath='{.data.username}' | base64 -d; echo
KUBECONFIG=.kube/config-${CLUSTER_NAME} kubectl get secret keycloak-initial-admin -n keycloak \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

### 2b. Switch to the `openshell` realm

Click the realm dropdown (top-left) and select **openshell**.

### 2c. Add GitHub as an Identity Provider

1. Navigate to **Identity Providers** > **Add provider** > **GitHub**
2. Configure:

   | Setting | Value |
   |---------|-------|
   | Alias | `github` |
   | Client ID | *(from Step 1)* |
   | Client Secret | *(from Step 1)* |
   | First Login Flow | `first broker login` (default) |
   | Sync mode | `import` |

3. Under **Advanced Settings**, set **Scopes**: `user:email read:user`
   - `user:email` — gives access to the user's private email
   - `read:user` — gives access to name and profile fields
4. Click **Save**

### 2d. Add attribute mappers (auto-import name and email)

After saving the IdP, go to the **Mappers** tab and add these mappers so profile fields are imported automatically from GitHub:

**Mapper 1: First Name**

| Setting | Value |
|---------|-------|
| Name | `first-name` |
| Sync mode override | `inherit` |
| Mapper type | `Attribute Importer` |
| Social Profile JSON Field Path | `name` |
| User Attribute Name | `firstName` |

> Note: GitHub provides a single `name` field. This maps the full name to firstName. See below for splitting.

**Mapper 2: Email**

| Setting | Value |
|---------|-------|
| Name | `email` |
| Sync mode override | `inherit` |
| Mapper type | `Attribute Importer` |
| Social Profile JSON Field Path | `email` |
| User Attribute Name | `email` |

**Mapper 3: Username**

| Setting | Value |
|---------|-------|
| Name | `username` |
| Sync mode override | `inherit` |
| Mapper type | `Username Template Importer` |
| Template | `${ALIAS}.${CLAIM.login}` or just `${CLAIM.login}` |

> **Name splitting:** GitHub provides a single `name` field (e.g., "Aleksander Slominski"). If you want proper first/last split, use mapper type `Attribute Importer` with JSON path `name` for firstName, and leave lastName blank — or handle it with a custom script mapper. For most CLI use cases, having the full name in firstName is sufficient.

### 2e. Disable VERIFY_PROFILE required action

By default, Keycloak requires users to verify their profile (email, first/last name) on first login. Since we import these from GitHub automatically, disable this:

1. Go to **Authentication** > **Required Actions**
2. Find **Verify Profile** and toggle it **OFF** (or set to disabled)

This prevents the "Update Account Information" form from appearing after GitHub login.

### 2f. Verify the redirect URI matches

After saving, Keycloak shows the **Redirect URI** at the top of the IdP config. Confirm it matches what you set in GitHub:

```
https://keycloak-${KEYCLOAK_NS}.${CLUSTER_DOMAIN}/realms/openshell/broker/github/endpoint
```

If it doesn't match, update the GitHub OAuth App callback URL.

> **Note:** No custom Keycloak image is needed. Standard Keycloak has GitHub as a built-in social IdP. Any GitHub user can now authenticate — access control happens via group membership (next step).

---

## Step 3: Create the `openshell-users` Authorization Group

### 3a. Create the group in Keycloak

1. In Keycloak Admin (openshell realm), go to **Groups**
2. Click **Create group**
3. Name: `openshell-users`
4. Save

### 3b. Add a group membership mapper to the OIDC client

The gateway needs to see group membership in the JWT token.

1. Go to **Clients** > click **openshell-cli** (Client details)
2. Click **Client scopes** tab > click **openshell-cli-dedicated**
3. Click **Add mapper** > **By configuration** > **Group Membership**
4. Configure:

   | Setting | Value |
   |---------|-------|
   | Name | `groups` |
   | Token Claim Name | `groups` |
   | Full group path | OFF |
   | Add to ID token | ON |
   | Add to access token | ON |

5. Save

This ensures the JWT includes a `groups` claim like `["openshell-users"]`.

### 3c. Alternative: Add mapper at realm level

If you want ALL clients in the openshell realm to see groups:

1. Go to **Client scopes** (realm level) > **roles** (or create a new scope)
2. Add the same Group Membership mapper there
3. Ensure it's in the "Default" assigned scopes

---

## Step 4: Authorize GitHub Users (Add to Group)

After a GitHub user logs in for the first time, Keycloak creates their account. An admin then adds them to the `openshell-users` group.

### Option A: Via Keycloak Admin UI

1. Go to **Users** > search for the GitHub username (e.g., `aslom`)
2. Click the user > **Groups** tab
3. Click **Join Group** > select `openshell-users`

### Option B: Via Keycloak Admin API (scriptable)

```bash
KC_URL="https://keycloak-${KEYCLOAK_NS}.${CLUSTER_DOMAIN}"

# Get admin credentials from cluster secret
KC_USER=$(kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.username}' | base64 -d)
KC_PASS=$(kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.password}' | base64 -d)

# Get admin token
TOKEN=$(curl -s "$KC_URL/realms/master/protocol/openid-connect/token" \
  -d "client_id=admin-cli" \
  -d "username=$KC_USER" \
  -d "password=$KC_PASS" \
  -d "grant_type=password" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Find user ID by username
USER_ID=$(curl -s "$KC_URL/admin/realms/openshell/users?username=aslom&exact=true" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')")

# Find group ID
GROUP_ID=$(curl -s "$KC_URL/admin/realms/openshell/groups?search=openshell-users&exact=true" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')")

# Add user to group
curl -s -X PUT "$KC_URL/admin/realms/openshell/users/$USER_ID/groups/$GROUP_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"

echo "User aslom added to openshell-users group"
```

### Option C: Pre-authorize before first login

You can create the user in Keycloak before they log in:

1. **Users** > **Add user**
2. Username: `aslom`
3. Save, then go to **Groups** tab > **Join Group** > `openshell-users`
4. Go to **Identity Provider Links** tab > **Link account**
   - Identity Provider: `github`
   - Provider User ID: *(GitHub numeric user ID — see below)*
   - Provider Username: `aslom`

To get a user's GitHub numeric ID:

```bash
curl -s https://api.github.com/users/aslom | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'id: {d[\"id\"]}  login: {d[\"login\"]}  name: {d.get(\"name\",\"\")}')"
# id: 1648338  login: aslom  name: Aleksander Slominski
```

When `aslom` logs in via GitHub, Keycloak links the accounts automatically.

---

## Step 5: Gateway Access Control

The gateway authenticates using OIDC tokens from Keycloak. Since GitHub login goes through Keycloak (as a broker), the gateway validates the Keycloak-issued JWT regardless of which upstream IdP was used.

### How access control works

```
GitHub user authenticates → Keycloak issues JWT with groups claim
→ Gateway validates JWT (issuer, audience, expiry)
→ Gateway checks groups claim contains "openshell-users" (if configured)
→ User gets access to their tenant sandbox
```

### Verify the OIDC issuer

The OIDC config is in `gateway.toml` (stored in the `openshell-gateway-config` ConfigMap):

```bash
KUBECONFIG=.kube/config-${CLUSTER_NAME} kubectl get configmap openshell-gateway-config -n ${TENANT} \
  -o jsonpath='{.data.gateway\.toml}' | grep -A2 "\[openshell.gateway.oidc\]"
```

Expected output:
```
[openshell.gateway.oidc]
issuer   = "https://keycloak-${KEYCLOAK_NS}.${CLUSTER_DOMAIN}/realms/openshell"
audience = "aslom"
```

### If the gateway doesn't check groups natively

If the current gateway only validates JWT signature + audience (without group-claim checking), access control is implicit:
- The user authenticates via Keycloak (valid JWT)
- The gateway allows requests from any valid JWT for its audience
- Sandbox operations are scoped to the tenant namespace

In this case, group membership is advisory — useful for future RBAC enforcement and for admin tooling to track who's authorized.

---

## Step 6: Test GitHub Login

### Via browser (Keycloak login page)

1. Open: `https://keycloak-${KEYCLOAK_NS}.${CLUSTER_DOMAIN}/realms/openshell/account`
2. Click **GitHub** on the login page
3. Authorize the OAuth App on GitHub
4. You should land on the Keycloak account page as your GitHub user

### Via kosh CLI (OIDC PKCE flow)

```bash
# The kosh CLI uses PKCE — when Keycloak shows the login page,
# click "GitHub" instead of entering username/password
kosh gateway login
```

### Via openshell CLI directly

```bash
openshell gateway login
# Browser opens → Keycloak login page → click GitHub → authorize
```

### Verify identity and group membership

```bash
# After login, check your identity
openshell sandbox list
# Should work without errors — confirms gateway accepted the Keycloak JWT

# Decode your token to verify groups claim
openshell gateway token | python3 -c "
import sys, json, base64
token = sys.stdin.read().strip().split('.')[1]
token += '=' * (-len(token) % 4)
claims = json.loads(base64.urlsafe_b64decode(token))
print(f'Username: {claims.get(\"preferred_username\")}')
print(f'Groups: {claims.get(\"groups\", [])}')
"
```

Expected output:
```
Username: aslom
Groups: ['openshell-users']
```

---

## Troubleshooting

### "Invalid redirect_uri" on GitHub

- The callback URL in the GitHub OAuth App doesn't match Keycloak's redirect URI
- Check: Keycloak IdP config shows the exact URI to use

### User logs in but has no group

- The user authenticated successfully but wasn't added to `openshell-users`
- Fix: Admin adds user to group (see Step 4)

### Keycloak login page doesn't show GitHub button

- The GitHub IdP wasn't added to the `openshell` realm (check you're in the right realm)
- The IdP is disabled — check **Identity Providers** and ensure it's enabled

### Gateway still requires password login

- The gateway doesn't choose the IdP — Keycloak's login page offers it
- If using ROPC (Resource Owner Password Credentials) flow, GitHub login won't work — ROPC bypasses the login page
- Solution: Use PKCE flow (browser-based) which shows the Keycloak login page with the GitHub button

### GitHub shows "Application suspended"

- The OAuth App may have been suspended due to inactivity or policy violation
- Check: <https://github.com/settings/developers> — ensure the app is active

---

## Architecture

```
User (kosh CLI)
    │
    │ OIDC PKCE flow (browser opens)
    ▼
Keycloak login page (openshell realm)
    │
    │ User clicks "Login with GitHub"
    ▼
GitHub OAuth (authorization code flow)
    │
    │ Returns auth code + user profile
    ▼
Keycloak (first broker login → creates/links user)
    │
    │ Checks: is user in "openshell-users" group?
    │ Issues JWT with groups claim
    ▼
Keycloak issues JWT (sub=github-user, iss=keycloak, groups=[openshell-users])
    │
    │ JWT with openshell realm claims
    ▼
OpenShell Gateway (validates JWT signature, issuer, audience)
    │
    │ mTLS + JWT
    ▼
Sandbox (tenant namespace: aslom)
```

---

## Optional: Org-Gated Login (Restrict to GitHub Org Members)

If you want to reject users who are NOT members of a specific GitHub org at login time (instead of post-login group management), see the custom Keycloak image approach:

1. Install custom image: `quay.io/aslomorg/github-org-keycloak:0.1.0-kc26.5.2`
2. Create a `github-org-gated` authentication flow with the "GitHub Org Member Check" execution
3. Set the org to `kaslomorg`
4. Use this flow as the IdP's "First Login Flow"

See PR #1981 for full details: <https://github.com/kagenti/kagenti/pull/1981>

> **Trade-off:** Org-gate is fail-closed at login (simpler ops, no post-login admin step), but requires a custom image and only works with public org membership. Group-based is standard Keycloak (no custom image), but requires an admin to explicitly grant access after first login.

---

## References

- PR #1981: <https://github.com/kagenti/kagenti/pull/1981>
- Issue #1980: GitHub login proof-of-concept
- Issue #1792: Social login for Kagenti UI
- GitHub OAuth Apps: <https://github.com/settings/developers>
- Keycloak IdP docs: <https://www.keycloak.org/docs/latest/server_admin/#github>
- Keycloak Group Mapper: <https://www.keycloak.org/docs/latest/server_admin/#_protocol-mappers>
