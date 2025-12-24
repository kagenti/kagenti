# Kagenti UI v2

Modern React-based UI for the Kagenti Cloud Native Agent Platform, built with PatternFly components to match the OpenShift console look and feel.

## Technology Stack

- **Frontend**: React 18 + TypeScript
- **UI Components**: PatternFly 5
- **State Management**: React Query (TanStack Query)
- **Routing**: React Router v6
- **Build Tool**: Vite
- **Backend**: FastAPI (Python)

## Project Structure

```
ui-v2/
├── src/
│   ├── components/     # Reusable UI components
│   ├── pages/          # Page components (routes)
│   ├── hooks/          # Custom React hooks
│   ├── services/       # API service layer
│   ├── contexts/       # React contexts (auth, etc.)
│   ├── types/          # TypeScript type definitions
│   └── styles/         # Global CSS and theme
├── public/             # Static assets
├── package.json
├── tsconfig.json
├── vite.config.ts
└── Dockerfile
```

## Development

### Prerequisites

- Node.js 20+
- npm or yarn

### Running Locally

```bash
# Install dependencies
npm install

# Start development server (port 3000)
npm run dev

# The frontend proxies /api/* requests to http://localhost:8000
# Make sure the backend is running
```

### Building for Production

```bash
npm run build
npm run preview  # Preview production build
```

### Linting

```bash
npm run lint
npm run typecheck
```

## Backend API

The frontend expects a FastAPI backend running at `/api/v1`. Key endpoints:

- `GET /api/v1/namespaces` - List Kubernetes namespaces
- `GET /api/v1/agents?namespace=X` - List agents
- `GET /api/v1/agents/{ns}/{name}` - Get agent details
- `GET /api/v1/tools?namespace=X` - List tools
- `GET /api/v1/tools/{ns}/{name}` - Get tool details
- `GET /api/v1/config/dashboards` - Get observability URLs

## Docker

```bash
# Build frontend image
docker build -t kagenti-ui:latest .

# Run with docker-compose (from deployments/ui-v2)
docker compose up --build
```

## Kubernetes Deployment

```bash
# Deploy with kustomize
kubectl apply -k ../deployments/ui-v2/kubernetes/

# Or apply individual manifests
kubectl apply -f ../deployments/ui-v2/kubernetes/
```

## Migration Status

This UI is part of the migration from Streamlit to React. Current status:

- [x] Phase 1: Foundation & Infrastructure
- [ ] Phase 2: Authentication & Core Layout
- [ ] Phase 3: Catalog Pages (Read-Only)
- [ ] Phase 4: Detail Pages & Interactions
- [ ] Phase 5: Chat & Real-time Features
- [ ] Phase 6: Import Wizards & Admin

## License

Apache 2.0 - See [LICENSE](../../LICENSE)
