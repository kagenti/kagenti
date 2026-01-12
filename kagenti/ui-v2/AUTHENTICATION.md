# Kagenti UI v2 - Authentication Guide

## Overview

The Kagenti UI v2 integrates with Keycloak for authentication using the OpenID Connect (OIDC) protocol. This document explains how authentication works and how to login.

## How Authentication Works

### Architecture

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Browser    │─────▶│  Backend API │─────▶│  Kubernetes  │
│  (React UI)  │◀─────│   (FastAPI)  │      │   Cluster    │
└──────────────┘      └──────────────┘      └──────────────┘
       │                                              
       │ OIDC Flow                                    
       ▼                                              
┌──────────────┐                                     
│   Keycloak   │                                     
│   (IdP)      │                                     
└──────────────┘                                     
```

### Authentication Flow

1. **Initial Load**: The UI fetches auth configuration from `/api/v1/auth/config`
2. **Check SSO**: Keycloak initializes with `onLoad: 'check-sso'` mode
   - If already logged in to Keycloak → automatic authentication
   - If NOT logged in → shows "Guest" with "Sign In" button
3. **Login**: User clicks "Sign In" → redirected to Keycloak login page
4. **Token**: After successful login, Keycloak returns JWT token
5. **Session**: Token is stored and auto-refreshed every 30 seconds

### Why It Shows "Guest"

The UI uses **passive authentication** (`check-sso`), which means:
- ✅ No forced login redirect on initial page load
- ✅ Users can browse anonymously if auth is optional for some features
- ❌ Requires user to click "Sign In" button explicitly

This is **by design** - it's not a bug!

## How to Login

### Method 1: Using the Sign In Button (Recommended)

1. Open the UI at: `http://kagenti-ui-v2.localtest.me:8080`
2. Look for the **"Sign In"** button in the top-right corner of the page
3. Click the button to be redirected to Keycloak
4. Enter your credentials and click "Sign in"
5. You'll be redirected back to the UI, now authenticated

### Method 2: Direct Keycloak Login (Pre-authenticate)

1. Navigate to: `http://keycloak.localtest.me:8080/realms/master/account`
2. Login with your credentials
3. Then navigate to: `http://kagenti-ui-v2.localtest.me:8080`
4. The UI will detect your existing Keycloak session automatically

## User Credentials

### Default Admin User

**⚠️ Warning**: Using the Keycloak admin account for daily use is not recommended!

```bash
# Get admin username (usually 'admin')
kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.username}' | base64 -d

# Get admin password
kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.password}' | base64 -d
```

### Creating a Regular User

Use the provided script to create a dedicated Kagenti user:

```bash
# Create user with default credentials
./scripts/create-kagenti-user.sh

# Or specify custom credentials
./scripts/create-kagenti-user.sh my-username my-password my-email@example.com
```

**Default credentials** (if using script without arguments):
- Username: `kagenti-admin`
- Password: `kagenti123`
- Email: `kagenti-admin@kagenti.local`

### Manual User Creation via Keycloak UI

1. Login to Keycloak Admin Console: `http://keycloak.localtest.me:8080/admin`
2. Navigate to: **Users** → **Add user**
3. Fill in:
   - Username: (your choice)
   - Email: (optional)
   - First/Last Name: (optional)
   - Email Verified: ✓
   - Enabled: ✓
4. Click **Create**
5. Go to **Credentials** tab
6. Set password and uncheck "Temporary"
7. Click **Set Password**

## Troubleshooting

### Issue: Always Shows "Guest"

**Possible Causes:**

1. **You haven't clicked "Sign In"**
   - Solution: Click the "Sign In" button in the top-right corner

2. **Backend auth is disabled**
   ```bash
   # Check if ENABLE_AUTH is set to true
   kubectl get secret kagenti-ui-oauth-secret -n kagenti-system \
     -o jsonpath='{.data.ENABLE_AUTH}' | base64 -d
   ```
   Should return: `true`

3. **Backend can't reach Keycloak**
   ```bash
   # Test from backend pod
   kubectl exec -n kagenti-system deployment/kagenti-backend -- \
     wget -O- http://keycloak.keycloak.svc.cluster.local:8080/realms/master
   ```

4. **Browser can't reach Keycloak**
   - Test in browser: `http://keycloak.localtest.me:8080/realms/master`
   - Should return JSON with realm info

### Issue: Login Redirect Fails

**Possible Causes:**

1. **Redirect URI mismatch**
   ```bash
   # Check configured redirect URI
   kubectl get secret kagenti-ui-oauth-secret -n kagenti-system \
     -o jsonpath='{.data.REDIRECT_URI}' | base64 -d
   ```
   Should be: `http://kagenti-ui-v2.localtest.me:8080/oauth2/callback`

2. **Client not registered in Keycloak**
   - Login to Keycloak Admin Console
   - Go to **Clients** → check for `kagenti` client
   - Verify **Valid Redirect URIs** includes: `http://kagenti-ui-v2.localtest.me:8080/*`

3. **Browser console errors**
   - Open browser DevTools (F12)
   - Check Console tab for Keycloak initialization errors
   - Check Network tab for failed API calls

### Issue: Token Refresh Fails

**Symptoms**: Logged out after 5 minutes

**Solution**: Check backend logs:
```bash
kubectl logs -n kagenti-system deployment/kagenti-backend --tail=50
```

### Debug Mode

Enable debug logging in the UI by opening browser console and running:
```javascript
localStorage.debug = 'kagenti:*'
```

Then refresh the page and check console for detailed auth flow logs.

## Security Considerations

### Production Deployment

For production deployments, ensure:

1. **Use HTTPS** for all endpoints (UI, backend, Keycloak)
2. **Strong passwords** for all user accounts
3. **Disable** the Keycloak admin account or use strong credentials
4. **Regular token rotation** (configured automatically)
5. **Short session timeouts** (adjust in Keycloak realm settings)
6. **Role-based access control** (configure in Keycloak)

### Token Storage

- Tokens are stored in React state (memory only)
- Tokens are NOT persisted to localStorage
- Automatic refresh every 30 seconds
- Tokens expire if user is inactive

### Keycloak client configuration and security rationale

This UI is a single-page application (SPA) running entirely in the browser. The Keycloak client used by the frontend is therefore configured following SPA best practices to avoid exposing secrets and to harden the OAuth2/OIDC flow:

- Client access type: **public (no client secret)** — SPAs cannot keep a client secret confidential. Using a confidential client would expose the secret to the browser and break the security model.
- PKCE (Proof Key for Code Exchange): **S256 enabled** — the authorization code flow is used with PKCE to mitigate code interception attacks. PKCE ensures that a stolen authorization code cannot be exchanged without the original code verifier.
- Standard flow (Authorization Code) enabled — preferred over the legacy implicit flow for improved security when used with PKCE.
- Redirect URIs: explicitly restricted to the UI host(s) (for example, `http://kagenti-ui-v2.localtest.me:8080/*` and `http://localhost:3000/*`) to prevent open-redirect attacks. Do not use wildcard redirects that allow arbitrary domains.
- Web origins / CORS: set to the UI origins only. Avoid permissive `*` in production.
- Public client + PKCE: this combination is the recommended approach for browser apps because it prevents secret exposure while maintaining the security guarantees of the authorization code flow.

Operational decisions and rationale:

- Tokens are kept in memory (React state) and are not persisted to localStorage or cookies by the frontend, reducing risk of token theft via XSS. The backend performs token validation for protected APIs.
- Short token lifetimes and automatic refresh reduce the window for token misuse. Consider using refresh token rotation on the server side for stronger guarantees.
- The UI uses `check-sso` (passive) on load so users are not forcibly redirected to Keycloak; this is a UX choice. If you need forced login, switch to `login-required` but ensure expected UX.
- Silent SSO iframe checks were disabled in this project due to stability/timeouts on some browsers and environments; if you re-enable them, ensure the `silent-check-sso.html` endpoint and iframe origin are correctly served and reachable.

Recommended Keycloak client settings (summary):

- Access Type: `public`
- Standard Flow Enabled: `true`
- Direct Access Grants: `false`
- PKCE Code Challenge Method: `S256`
- Valid Redirect URIs: explicit UI callback URLs
- Web Origins: explicit UI origins (avoid `*` in production)

For server-side components (backend, services) that need to perform privileged operations, continue to use confidential clients or service accounts where secrets are kept on the server and never shipped to the browser.

Following these settings aligns the UI with current OAuth2/OIDC best practices for SPAs and the guidance used in the OpenShift/PatternFly ecosystem: avoid exposing secrets, use PKCE + authorization code flow, restrict redirect URIs, validate tokens server-side, and prefer in-memory token handling on the client.

## Configuration Reference

### Backend Environment Variables

From `kagenti-ui-oauth-secret`:

- `ENABLE_AUTH`: Set to `"true"` to enable authentication
- `AUTH_ENDPOINT`: Keycloak authorization endpoint
- `TOKEN_ENDPOINT`: Keycloak token endpoint
- `CLIENT_ID`: OAuth2 client ID (usually `kagenti`)
- `CLIENT_SECRET`: OAuth2 client secret (auto-generated)
- `REDIRECT_URI`: OAuth2 callback URL
- `SCOPE`: OAuth2 scopes (default: `openid profile email`)

### Frontend Configuration

The frontend gets configuration dynamically from `/api/v1/auth/config`:

```json
{
  "enabled": true,
  "keycloak_url": "http://keycloak.localtest.me:8080",
  "realm": "master",
  "client_id": "kagenti",
  "redirect_uri": "http://kagenti-ui-v2.localtest.me:8080/oauth2/callback"
}
```

No build-time environment variables needed! ✨

## API Endpoints

### Public Endpoints (no auth required)

- `GET /api/v1/auth/config` - Get auth configuration
- `GET /api/v1/auth/status` - Check auth status

### Protected Endpoints (auth required)

- `GET /api/v1/auth/userinfo` - Get current user info
- `GET /api/v1/agents` - List agents
- `POST /api/v1/agents/{ns}/{name}/chat` - Chat with agent
- (all other API endpoints)

---

## Page-Level Access Control

### Overview

The UI implements page-level access control to protect sensitive resources:

- **Guest users** (unauthenticated) can only access the **Home page**
- **Authenticated users** have access to all pages and features
- The design supports future **role-based access control (RBAC)**

### Current Behavior

#### Guest Users
- ✅ Can view Home page
- ❌ Cannot access any other pages
- 🔒 Clicking protected links shows "Authentication Required" prompt
- 📋 Sidebar shows only "Home" navigation item

#### Authenticated Users
- ✅ Full access to all pages
- ✅ Complete sidebar navigation
- 👤 User profile displayed in masthead
- 🔑 Access controlled by authentication state

### Protected Pages

All pages except Home require authentication:

- `/agents` - Agent Catalog
- `/agents/import` - Import Agent
- `/agents/:namespace/:name` - Agent Details
- `/tools` - Tool Catalog
- `/tools/import` - Import Tool
- `/tools/:namespace/:name` - Tool Details
- `/mcp-gateway` - MCP Gateway
- `/ai-gateway` - AI Gateway
- `/gateway-policies` - Gateway Policies
- `/observability` - Observability
- `/admin` - Administration

### Implementation Details

Protected routes use the `<ProtectedRoute>` component wrapper:

```tsx
// In App.tsx
<Route path="/agents" element={
  <ProtectedRoute>
    <AgentCatalogPage />
  </ProtectedRoute>
} />
```

The component handles:
1. Loading state while checking authentication
2. Login prompt for unauthenticated users
3. Access control based on roles (future)
4. Rendering protected content for authorized users

### Future: Role-Based Access Control (RBAC)

The architecture supports future RBAC implementation:

```tsx
// Example: Admin-only page
<ProtectedRoute requiredRoles={['admin', 'operator']}>
  <AdminPage />
</ProtectedRoute>

// Example: Namespace-specific access (planned)
<ProtectedRoute requiredNamespace="team1">
  <AgentDetailPage />
</ProtectedRoute>
```

**Roles are extracted from Keycloak tokens:**
- `realm_access.roles` - Realm-level roles
- `resource_access[client_id].roles` - Client-specific roles

**To implement RBAC in the future:**

1. Define roles in Keycloak (e.g., `viewer`, `editor`, `admin`)
2. Assign roles to users/groups
3. Add `requiredRoles` prop to protected routes
4. Backend API must enforce same authorization rules

### Security Considerations

⚠️ **Important**: Client-side protection is **not security**. It only controls UI visibility. The backend API **must** enforce authorization for all operations.

- UI protection prevents accidental access
- Backend protection prevents unauthorized API calls
- Both layers work together for complete security

### Testing Access Control

**As Guest:**
```bash
# Open UI without signing in
open http://kagenti-ui.localtest.me:8080

# Try to access protected page - should show login prompt
open http://kagenti-ui.localtest.me:8080/agents
```

**As Authenticated User:**
1. Sign in via "Sign In" button
2. Verify full navigation appears
3. Access all pages successfully
4. Check user info in masthead

---

## Additional Resources

- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [OpenID Connect Specification](https://openid.net/specs/openid-connect-core-1_0.html)
- [Keycloak JS Adapter](https://www.keycloak.org/docs/latest/securing_apps/#_javascript_adapter)
- [PatternFly Authentication Patterns](https://www.patternfly.org/patterns/authentication/)

## Need Help?

If you're still having issues:

1. Check browser console for errors (F12 → Console)
2. Check backend logs: `kubectl logs -n kagenti-system deployment/kagenti-backend`
3. Verify Keycloak is running: `kubectl get pods -n keycloak`
4. Test Keycloak accessibility: `http://keycloak.localtest.me:8080`
5. Open an issue on GitHub with logs and error messages
