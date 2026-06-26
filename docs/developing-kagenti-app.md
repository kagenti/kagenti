# Developing a Kagenti Application

This guide explains how to build applications that integrate with the Kagenti platform, using the [app-demo example](../kagenti/examples/app-demo/) as a reference implementation.

## Architecture Overview

When building a third-party application that integrates with Kagenti, you typically use a **two-backend architecture**:

```
Browser  ──OIDC──>  Keycloak (client: your-app)
   │
   └── http://your-app.localtest.me:8080
         │
    ┌────┴────┐
    │ nginx   │  frontend (React SPA + /api proxy)
    │ React   │
    └────┬────┘
         │ /api/*
    ┌────┴────────┐
    │ FastAPI      │  your app backend (BFF proxy)
    └────┬────────┘
         │ forward Bearer token
    ┌────┴────────────┐
    │ Kagenti Backend  │  (platform API)
    └─────────────────┘
```

### 1. Your Application Backend (BFF - Backend for Frontend)

**Purpose:** A lightweight proxy service that acts as a Backend-for-Frontend (BFF) pattern.

**Key responsibilities:**
- Receives requests from your frontend application
- Forwards authenticated requests to the Kagenti Backend
- Passes through the user's JWT Bearer token from Keycloak
- Simplifies the frontend by providing a single API endpoint
- Handles response transformation (e.g., streaming to JSON conversion)

**Example implementation:** See [`kagenti/examples/app-demo/backend/`](../kagenti/examples/app-demo/backend/)

The app-demo backend is a FastAPI service that:
- Proxies `/api/v1/namespaces` → Kagenti Backend
- Proxies `/api/v1/agents` → Kagenti Backend  
- Proxies `/api/v1/chat/{namespace}/{name}/stream` → Kagenti Backend (with streaming-to-JSON conversion)
- Provides auth configuration to the frontend

### 2. Kagenti Backend (Platform API)

**Purpose:** The main Kagenti platform backend that powers the Kagenti Dashboard and provides the core platform APIs.

**Key responsibilities:**
- Manages agents, namespaces, and workloads via Kubernetes APIs
- Handles authentication and authorization with Keycloak
- Provides the core API for interacting with the Kagenti platform
- Serves the Kagenti Dashboard UI
- Manages feature flags, integrations, and platform configuration

**Location:** Deployed as part of the Kagenti platform (see [`charts/kagenti/templates/ui.yaml`](../charts/kagenti/templates/ui.yaml))

## Why Two Backends?

The BFF (Backend-for-Frontend) pattern provides several advantages:

### 1. Separation of Concerns
- Your application backend is application-specific
- Kagenti Backend is platform-wide and shared across all applications
- Each can evolve independently

### 2. Simplified Frontend
- The BFF shields your frontend from complex streaming APIs
- Provides a stable, application-specific API contract
- Handles response transformation (e.g., SSE streams → JSON)

### 3. Token Management
- The BFF handles JWT token forwarding transparently
- Centralizes authentication logic
- Simplifies frontend code

### 4. Response Transformation
- Converts Server-Sent Events (SSE) streams to simple JSON responses
- Aggregates multiple API calls into single responses
- Provides easier-to-consume data formats for your frontend

### 5. Independent Development
- Third-party apps can add custom logic without modifying the platform
- Easier testing and mocking
- Better control over error handling and retries



## Should You Work Against Kagenti Backend or Directly with APIs?

The choice depends on your use case:

### Use Kagenti Backend API When:

✅ **Building user-facing applications** - Like the app-demo, where users interact with agents through a web interface

✅ **Need built-in authentication/authorization** - Leverage Keycloak integration without implementing it yourself

✅ **Want higher-level abstractions** - Work with agents and namespaces instead of raw Kubernetes resources

✅ **Require consistent API contracts** - The Kagenti Backend provides stable APIs across platform versions

✅ **Leverage existing agent management features** - Discovery, lifecycle management, and monitoring

**Example use cases:**
- Web applications for end users
- Mobile apps
- Chatbots and conversational interfaces
- Custom dashboards

### Use Keycloak + Kagenti APIs Directly When:

✅ **Building infrastructure automation** - CI/CD pipelines, deployment scripts

✅ **Need fine-grained control** - Direct access to Kubernetes resources and CRDs

✅ **Implementing custom authentication flows** - Beyond standard OAuth/OIDC

✅ **Want to bypass the platform layer** - For performance or specific requirements

✅ **Building administrative tools** - That need direct cluster access

**Example use cases:**
- Infrastructure-as-Code tools
- Custom operators or controllers
- Administrative CLIs
- Monitoring and alerting systems

## Recommendation for Application Developers

For most **application developers**, we recommend:

1. **Use the Kagenti Backend API** as shown in the app-demo
2. Implement a **lightweight BFF** if you need:
   - Response transformation
   - Application-specific logic
   - Custom error handling
   - API aggregation
3. Let the Kagenti Backend handle:
   - Authentication and authorization
   - Kubernetes interactions
   - Agent lifecycle management
   - Platform integrations

This approach gives you the best balance of:
- **Simplicity** - Focus on your application logic
- **Security** - Leverage platform authentication
- **Maintainability** - Isolate from platform changes
- **Flexibility** - Add custom logic in your BFF

## Getting Started

To build your own Kagenti application:

1. **Review the app-demo example:** [`kagenti/examples/app-demo/`](../kagenti/examples/app-demo/)
2. **Set up authentication:** Register your OAuth client with Keycloak
3. **Implement your BFF:** Use the app-demo backend as a template
4. **Build your frontend:** Connect to your BFF, which proxies to Kagenti Backend
5. **Deploy:** Use Kubernetes manifests similar to the app-demo

For detailed implementation guidance, see the [app-demo README](../kagenti/examples/app-demo/README.md).

## API Reference

The Kagenti Backend provides the following key endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/namespaces` | GET | List available namespaces |
| `/api/v1/agents` | GET | List agents (optionally filtered by namespace) |
| `/api/v1/agents/{namespace}/{name}` | GET | Get agent details |
| `/api/v1/chat/{namespace}/{name}/stream` | POST | Send a message to an agent (SSE stream) |

All endpoints require a valid JWT Bearer token from Keycloak in the `Authorization` header.

## Example: Minimal BFF Implementation

Here's a minimal FastAPI BFF that proxies requests to Kagenti Backend:

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx

app = FastAPI()

KAGENTI_API_URL = "http://kagenti-backend.kagenti-system.svc.cluster.local:8000"

@app.get("/api/v1/agents")
async def list_agents(request: Request, namespace: str = ""):
    async with httpx.AsyncClient(base_url=KAGENTI_API_URL) as client:
        headers = {}
        if auth := request.headers.get("authorization"):
            headers["Authorization"] = auth
        
        path = f"/api/v1/agents?namespace={namespace}" if namespace else "/api/v1/agents"
        resp = await client.get(path, headers=headers)
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
```

For a complete implementation with streaming support, error handling, and authentication, see the [app-demo backend](../kagenti/examples/app-demo/backend/).

## Next Steps

- **Explore the app-demo:** [`kagenti/examples/app-demo/`](../kagenti/examples/app-demo/)
- **Learn about authentication:** [Identity Guide](./identity-guide.md)
- **Deploy your first agent:** [New Agent Guide](./new-agent.md)
- **Understand the platform:** [Technical Details](./tech-details.md)