# Rossoctl App Demo

A standalone demo application that shows how a third-party app integrates with the Rossoctl platform: authenticate via Keycloak, discover deployed agents, and send tasks.

> **📖 For architecture details and development guidance**, see the [Developing a Rossoctl Application Guide](../../../docs/developing-rossoctl-app.md).

## Quick Start

**Prerequisites:**
- A running Rossoctl Kind cluster with UI enabled
- At least one agent deployed in any namespace (e.g., follow the [Weather Agent Demo](https://github.com/rossoctl/cortex/blob/main/authbridge/demos/weather-agent/demo-ui.md))
- Users created in Keycloak (default users: `alice`, `bob`, `charlie`)

> **💡 Note:** The app-demo works with the `rossoctl` realm in Keycloak and can discover agents in any namespace. You don't need a specific namespace like "team1" - the app dynamically lists all available namespaces with agents.

### 1. Deploy the App

```bash
cd rossoctl/examples/app-demo

# One command: build images, load into Kind, register Keycloak client, deploy
make all
```

**What this does:**
- Builds frontend (React) and backend (FastAPI) container images
- Loads images into your Kind cluster
- Registers the `app-demo` OAuth client with Keycloak
- Creates the `rossoctl-operator` realm role
- Deploys the application to the `rossoctl-system` namespace

> **⚠️ After deployment**, you must grant user access to agents before they appear in the app. See step 3 below.

### 2. Configure User Permissions

Assign the `rossoctl-operator` role to users who should be able to send tasks to agents.

**Assign rossoctl-operator role to users in Keycloak:**

1. Open `http://keycloak.localtest.me:8080/admin` and sign in
   - Get credentials: `.github/scripts/local-setup/show-services.sh`
2. Select the **rossoctl** realm (dropdown in the top-left)
3. Go to **Users** → select a user (e.g., `alice`)
4. **Role mapping** tab → **Assign role**
5. Filter by realm roles → select **rossoctl-operator** → **Assign**

> **💡 Tip:** Any authenticated user can browse agents. Only users with `rossoctl-operator` can send tasks.

### 3. Grant Access to Agents

Agents protected by AuthBridge require a Keycloak audience scope so that user tokens include the agent's identity. Without this, agents won't appear in the app.

**Option A — Automated (for demo agents):**

```bash
make grant-agent-access
```

This configures access for the pre-defined demo agents (weather-agent, git-issue-agent in team1).

**Option B — Manual (for any agent):**

Follow the step-by-step Keycloak instructions in **[docs/agent-access-setup.md](docs/agent-access-setup.md)**.

> **⚠️ After granting access**, users must log out and back in to receive updated tokens.

### 4. Use the App

1. Open `http://app-demo.localtest.me:8080` in an **incognito/private window**
   - This ensures you don't reuse the admin token from step 2
2. Click **Sign In with Keycloak**
3. Log in with a user that has the `rossoctl-operator` role (e.g., `alice`)
4. **Browse agents:**
   - Select a namespace from the dropdown
   - View available agents in that namespace
5. **Send a task:**
   - Click on an agent card
   - Type your task in the input field
   - Click **Send**
   - View the agent's response
6. **Continue:**
   - Click **New Task** to send another task to the same agent
   - Click **Back to Agents** to select a different agent

**Troubleshooting:**
- If you see "Forbidden" errors, ensure the user has the `rossoctl-operator` role and has logged out/in after role assignment
- If agents don't appear, the user's token may be missing the agent's audience claim — see [Agent Access Setup](docs/agent-access-setup.md) for how to configure Keycloak
- Check browser console for detailed error messages

## Advanced Usage

### Individual Deployment Steps

If you need more control, you can run each step separately. Each step automatically includes its prerequisites:

```bash
make build                # Build frontend and backend container images
make kind-load            # Build + load images into Kind cluster
make keycloak-setup       # Build + load + register Keycloak OAuth client
make deploy               # Build + load + keycloak + deploy to cluster
make all                  # All of the above (recommended)
make grant-agent-access   # Configure audience scopes for demo agents
```

### Assigning Roles via CLI

For automation or scripting, you can assign the `rossoctl-operator` role via kubectl:

```bash
KC_ADMIN_USER=$(kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.username}' | base64 -d)
KC_ADMIN_PASS=$(kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.password}' | base64 -d)

# Assign rossoctl-operator to a user (replace alice with the target username)
kubectl exec -n keycloak keycloak-0 -- \
  /opt/keycloak/bin/kcadm.sh add-roles -r rossoctl \
  --uname alice --rolename rossoctl-operator \
  --no-config --server http://localhost:8080 \
  --realm master --user "$KC_ADMIN_USER" --password "$KC_ADMIN_PASS"
```

> **⚠️ Important:** After assigning the role, the user must **log out and log back in** for the new role to appear in their token.

### Role Permissions

| Realm role | Permissions |
|-----------|-------------|
| *(any authenticated user)* | List agents, view agent cards |
| `rossoctl-operator` | Send tasks to agents |

### Local Development

For development without rebuilding containers, you can run the frontend and backend locally:

#### Prerequisites for Local Development

- Python 3.11+ with `pip` or `uv`
- Node.js 18+ with `npm`
- Access to a running Rossoctl cluster (Kind or remote)

#### Backend Development

Run the FastAPI backend locally with hot reload:

```bash
cd backend

# Create virtualenv and install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Configure environment variables
export ROSSOCTL_API_URL=http://rossoctl-backend.localtest.me:8080  # Point to Rossoctl Backend
export KEYCLOAK_PUBLIC_URL=http://keycloak.localtest.me:8080
export KEYCLOAK_REALM=rossoctl
export CLIENT_ID=app-demo
export ENABLE_AUTH=false  # Set to true to test with Keycloak authentication

# Start the backend with hot reload
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The backend will be available at `http://localhost:8000`. API endpoints:
- `GET /health` - Health check
- `GET /api/v1/namespaces` - List namespaces
- `GET /api/v1/agents` - List agents
- `POST /api/v1/chat/{namespace}/{name}/send` - Send message to agent
- `POST /api/v1/token-broker/session` - Create Token Broker session (if configured)
- `GET /api/v1/token-broker/ui-events` - Long-poll for Token Broker UI events (no timeout)
- `DELETE /api/v1/token-broker/session` - End Token Broker session

#### Frontend Development

Run the React frontend with Vite dev server:

```bash
cd frontend

# Install dependencies
npm install

# Start Vite dev server (proxies /api/* to backend at :8000)
npm run dev
```

The frontend will be available at `http://localhost:3000` with hot module replacement (HMR).

**Development workflow:**
1. Make changes to backend code → auto-reloads
2. Make changes to frontend code → HMR updates browser
3. Test the full flow: Frontend → Backend → Rossoctl Backend

**Testing with authentication:**
- Set `ENABLE_AUTH=true` in backend
- Ensure Keycloak is accessible
- Use browser dev tools to inspect JWT tokens

### Debugging Tips

**Backend issues:**
- Check logs: `kubectl logs -n rossoctl-system deployment/app-demo-backend -f`
- Verify Rossoctl Backend is accessible: `curl http://rossoctl-backend.rossoctl-system.svc.cluster.local:8000/health`
- Test without auth: Set `ENABLE_AUTH=false` to isolate authentication issues

**Frontend issues:**
- Check browser console for errors
- Verify backend is accessible: `curl http://localhost:8000/health`
- Check network tab for failed API calls

**Authentication issues:**
- Verify user has `rossoctl-operator` role in Keycloak
- Check JWT token in browser dev tools (Application → Storage → Local Storage)
- Ensure user logged out/in after role assignment
- Try incognito mode to clear cached tokens

## Technical Details

### Stack

| Component | Technology |
|-----------|-----------|
| Frontend | React 18, TypeScript, Vite, PatternFly 5 |
| Backend | Python 3.11+, FastAPI, httpx |
| Auth | Keycloak OIDC (keycloak-js, PKCE S256) |
| Container | Docker multi-stage builds |
| Deployment | Kubernetes manifests (Gateway API HTTPRoute) |

### Configuration

The backend reads configuration from environment variables (see `k8s/configmap.yaml`):

| Variable | Description | Default |
|----------|-------------|---------|
| `ROSSOCTL_API_URL` | Rossoctl backend URL | `http://rossoctl-backend.rossoctl-system.svc.cluster.local:8000` |
| `KEYCLOAK_PUBLIC_URL` | Keycloak URL (browser) | `http://keycloak.localtest.me:8080` |
| `KEYCLOAK_REALM` | Keycloak realm | `rossoctl` |
| `CLIENT_ID` | OAuth client ID | `app-demo` |
| `ENABLE_AUTH` | Enable authentication | `true` |
| `TOKEN_BROKER_URL` | Token Broker service URL (empty = disabled) | `""` |

### Project Structure

```
app-demo/
├── backend/              # FastAPI BFF (Backend for Frontend)
│   ├── app/
│   │   ├── main.py      # FastAPI app entry point
│   │   ├── config.py    # Configuration settings
│   │   ├── token_broker.py  # Token Broker client (optional)
│   │   └── routes/      # API route handlers
│   │       ├── agents.py        # Agent listing endpoints
│   │       ├── chat.py          # Chat/task endpoints
│   │       ├── auth_config.py   # Auth configuration
│   │       └── token_broker.py  # Token Broker session & events
│   ├── Dockerfile       # Multi-stage build
│   └── pyproject.toml   # Python dependencies
├── frontend/            # React SPA
│   ├── public/
│   │   └── oauth-complete.html  # OAuth popup completion page
│   ├── src/
│   │   ├── components/  # React components
│   │   ├── contexts/    # Auth context
│   │   ├── pages/       # Page components
│   │   └── services/    # API client
│   ├── Dockerfile       # Multi-stage build with nginx
│   └── package.json     # Node dependencies
├── k8s/                 # Kubernetes manifests
│   ├── backend-deployment.yaml
│   ├── frontend-deployment.yaml
│   ├── configmap.yaml
│   └── httproute.yaml   # Gateway API routing
├── keycloak/            # Keycloak setup scripts
│   ├── register_client.py      # App client + role registration
│   └── grant_agent_access.py   # Per-agent audience scope setup
├── docs/               # Documentation
│   └── agent-access-setup.md  # How to grant agent access (manual steps)
└── Makefile            # Build and deployment automation
```

## Token Broker Integration (Optional)

The app-demo optionally integrates with the **Token Broker** service for OAuth token management with AI agents. When an agent needs to access an OAuth-protected resource (e.g., GitHub API via MCP), the Token Broker coordinates the OAuth flow with the user.

### How It Works

1. The backend checks `TOKEN_BROKER_URL` at runtime — if empty, the feature is disabled and chat works as normal
2. When enabled, the frontend creates a Token Broker session after login (`POST /sessions`)
3. The backend continuously polls Token Broker for broker-events (`POST /sessions/broker-events`) with no timeout and queues them internally
4. The frontend long-polls the backend for UI events (`GET /token-broker/ui-events`) with no timeout
5. If an agent triggers an OAuth flow, Token Broker returns an `oauth_url_ready` event with an authorization URL
5. The frontend opens the authorization URL in a popup window
6. After the user authorizes, Token Broker redirects the popup to the app's `oauth-complete.html` page
7. The popup posts the result back to the main window and closes
8. Token Broker delivers the OAuth token to the agent behind the scenes

### Enabling Token Broker

Set the `TOKEN_BROKER_URL` environment variable to the Token Broker service address:

```bash
# In k8s/configmap.yaml or via environment variable
TOKEN_BROKER_URL=http://token-broker.rossoctl-system.svc.cluster.local:8190
```

### Token Broker API

The backend uses three Token Broker service endpoints (all authenticated with the user's Keycloak JWT) and exposes one UI endpoint to the frontend:

**Token Broker Service API (backend → Token Broker):**

| Endpoint | Purpose |
|----------|---------|
| `POST /sessions` | Create an OAuth session (includes a redirect URL for completion) |
| `POST /sessions/broker-events` | Long-poll for broker-events (no timeout, waits indefinitely for `oauth_url_ready` or other events) |
| `POST /sessions/end` | End session and release resources |

**App-Demo Backend API (frontend → backend):**

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/token-broker/ui-events` | Long-poll for UI events (no timeout, waits indefinitely for queued events) |

### OAuth Completion Flow

After the user authorizes in the popup:
- **Success**: Token Broker redirects to `<redirect_url>?oauth_status=success`
- **Error**: Token Broker redirects to `<redirect_url>?oauth_status=error&error=<code>&error_description=<msg>`

The `oauth-complete.html` page reads these parameters, posts a message to the opener window, and closes.

### Architecture

```
User Browser
    ↓ (Keycloak JWT)
React Frontend ←────── long-poll ──────→ FastAPI Backend
    ↓ (popup)                                ↓ (poll loop)
OAuth Provider ←── redirect ──→ Token Broker
                                     ↓
                                AI Agent → MCP Server (OAuth protected)
```

## Clean Up

Remove the app-demo from your cluster:

```bash
make clean
```

This will:
- Delete the app-demo deployments and services
- Remove the Keycloak OAuth client
- Clean up the HTTPRoute configuration

## Learn More

- **[Developing a Rossoctl Application Guide](../../../docs/developing-rossoctl-app.md)** - Architecture, design patterns, and best practices
- **[Identity Guide](../../../docs/identity-guide.md)** - Authentication and authorization details
- **[Rossoctl Documentation](../../../README.md)** - Full platform documentation
