# Kagenti Backend API

FastAPI-based REST API backend for the Kagenti UI, providing endpoints for managing AI agents and MCP tools on Kubernetes.

## Technology Stack

- **Framework**: FastAPI
- **Python**: 3.11+
- **Package Manager**: uv
- **Kubernetes Client**: kubernetes-client/python

## Project Structure

```
backend/
├── app/
│   ├── core/           # Configuration and constants
│   ├── models/         # Pydantic models
│   ├── routers/        # API route handlers
│   ├── services/       # Business logic and K8s client
│   └── main.py         # Application entry point
├── tests/              # Test files
├── pyproject.toml
└── Dockerfile
```

## Development

### Prerequisites

- Python 3.11+
- uv (recommended) or pip
- Access to a Kubernetes cluster (kubeconfig or in-cluster)

### Running Locally

```bash
cd kagenti/backend

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install -e .

# Run development server
uvicorn app.main:app --reload --port 8000

# Or
python -m app.main
```

### API Documentation

Once running, access the OpenAPI documentation:

- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc
- OpenAPI JSON: http://localhost:8000/api/openapi.json

## API Endpoints

### Health
- `GET /health` - Liveness check
- `GET /ready` - Readiness check

### Authentication
- `GET /api/v1/auth/config` - Get authentication configuration for frontend initialization
- `GET /api/v1/auth/status` - Get authentication status and configuration
- `GET /api/v1/auth/userinfo` - Get current user information (requires authentication)
- `GET /api/v1/auth/me` - Get current user information (requires authentication)

### Namespaces
- `GET /api/v1/namespaces` - List available Kubernetes namespaces (with optional `enabled_only` filter)

### Agents
- `GET /api/v1/agents` - List all agents across namespaces
- `GET /api/v1/agents/{namespace}/{name}` - Get specific agent details
- `GET /api/v1/agents/{namespace}/{name}/route-status` - Check HTTPRoute/Route status for agent
- `DELETE /api/v1/agents/{namespace}/{name}` - Delete agent
- `POST /api/v1/agents` - Create new agent (supports deployment from image or source code via Shipwright)
- `GET /api/v1/agents/build-strategies` - List available ClusterBuildStrategy resources
- `GET /api/v1/agents/{namespace}/{name}/shipwright-build` - Get Shipwright build status
- `GET /api/v1/agents/{namespace}/{name}/shipwright-buildrun` - Get latest Shipwright BuildRun status
- `POST /api/v1/agents/{namespace}/{name}/shipwright-buildrun` - Trigger new Shipwright BuildRun
- `GET /api/v1/agents/{namespace}/{name}/shipwright-build-info` - Get full Shipwright build information
- `POST /api/v1/agents/{namespace}/{name}/finalize-shipwright-build` - Finalize agent creation after successful build
- `POST /api/v1/agents/parse-env` - Parse environment file content
- `POST /api/v1/agents/fetch-env-url` - Fetch and parse environment file from URL

### Tools
- `GET /api/v1/tools` - List all MCP tools across namespaces
- `GET /api/v1/tools/{namespace}/{name}` - Get specific tool details
- `GET /api/v1/tools/{namespace}/{name}/route-status` - Check HTTPRoute/Route status for tool
- `DELETE /api/v1/tools/{namespace}/{name}` - Delete tool
- `POST /api/v1/tools` - Create new tool (supports deployment from image or source code via Shipwright)
- `GET /api/v1/tools/{namespace}/{name}/shipwright-build-info` - Get full Shipwright build information
- `POST /api/v1/tools/{namespace}/{name}/shipwright-buildrun` - Trigger new Shipwright BuildRun
- `POST /api/v1/tools/{namespace}/{name}/finalize-shipwright-build` - Finalize tool creation after successful build
- `POST /api/v1/tools/{namespace}/{name}/connect` - Connect to MCP tool and list available tools
- `POST /api/v1/tools/{namespace}/{name}/invoke` - Invoke an MCP tool with specified arguments

### Chat (A2A Protocol)
- `GET /api/v1/chat/{namespace}/{name}/agent-card` - Fetch A2A agent card describing capabilities
- `POST /api/v1/chat/{namespace}/{name}/send` - Send message to A2A agent
- `POST /api/v1/chat/{namespace}/{name}/stream` - Stream chat with A2A agent (Server-Sent Events)

### Configuration
- `GET /api/v1/config/dashboards` - Get dashboard URLs for observability tools (Phoenix, Kiali, MCP Inspector, Keycloak)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `false` | Enable debug mode |
| `DOMAIN_NAME` | `localtest.me` | Domain for service URLs |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed CORS origins |

## Docker

```bash
# Build image
docker build -t kagenti-backend:latest .

# Run container
docker run -p 8000:8000 -v ~/.kube/config:/home/appuser/.kube/config:ro kagenti-backend:latest
```

## Testing

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest
```

## License

Apache 2.0 - See [LICENSE](../../LICENSE)
