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

### Namespaces
- `GET /api/v1/namespaces` - List namespaces

### Agents
- `GET /api/v1/agents` - List agents
- `GET /api/v1/agents/{namespace}/{name}` - Get agent
- `DELETE /api/v1/agents/{namespace}/{name}` - Delete agent

### Tools
- `GET /api/v1/tools` - List MCP tools
- `GET /api/v1/tools/{namespace}/{name}` - Get tool
- `DELETE /api/v1/tools/{namespace}/{name}` - Delete tool

### Configuration
- `GET /api/v1/config/dashboards` - Get dashboard URLs

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
