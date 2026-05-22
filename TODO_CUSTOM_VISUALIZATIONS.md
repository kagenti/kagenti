# TODO: Custom Visualizations - MLflow API Proxy, Kiali API, Custom Graphs

## Passover Document

This document captures the full scope of work for building custom trace/mesh
visualizations in the Kagenti UI. Start a new worktree and a new Claude instance
for this work.

---

## 1. Overview

The Kagenti UI currently links out to external dashboards (MLflow, Phoenix, Kiali)
for observability. This initiative adds:

1. **MLflow API proxy** in the Kagenti backend — direct access to trace data
2. **Kiali API proxy** — read-only access to service mesh data (RBAC-scoped)
3. **Custom graph visualizations** — interactive graphs in the Kagenti UI based on
   trace and mesh data, going beyond the tree view
4. **Trace-mesh correlation** — linking LLM traces with service mesh traffic

---

## 2. MLflow API Proxy

### 2.1 Goal

Expose MLflow trace data through the Kagenti backend API so the UI can build
custom visualizations without navigating to external MLflow UI.

### 2.2 Required Backend Work

- **New router**: `kagenti/backend/app/routers/mlflow_proxy.py`
- **Endpoints** (under `/api/v1/mlflow/`):
  - `GET /experiments` — list experiments
  - `GET /experiments/{id}/traces` — list traces for an experiment
  - `GET /traces/{trace_id}` — get trace detail with spans
  - `GET /traces/{trace_id}/spans` — get all spans for a trace
  - `GET /traces/search` — search traces by attributes (agent name, namespace, time range)
- **Auth**: Forward Keycloak token to MLflow (mlflow-oidc-auth accepts the same tokens)
- **Config**: MLflow URL from `kagenti-config` ConfigMap or env var
- **RBAC consideration**: Namespace-scoped filtering of traces based on user's namespace access

### 2.3 MLflow REST API Reference

MLflow exposes REST API at `<MLFLOW_URL>/api/2.0/mlflow/`:
- `GET /experiments/search` — search experiments
- `GET /experiments/get?experiment_id=X` — get experiment
- `GET /ajax-api/2.0/mlflow/traces?experiment_id=X` — list traces (newer MLflow)
- `GET /ajax-api/2.0/mlflow/traces/{request_id}` — trace detail

The mlflow-oidc-auth plugin protects these with OIDC tokens. The Kagenti backend
already has the auth middleware to obtain tokens.

### 2.4 Current State

- MLflow is deployed via Helm chart with mlflow-oidc-auth plugin
- Auth flows documented in `docs/auth/keycloak-patterns.md`
- `auth:mlflow-oidc-auth` skill covers the OIDC setup
- OpenTelemetry Collector sends traces to MLflow via OTLP with OAuth2 client credentials
- Traces have GenAI semantic convention attributes (model, tokens, etc.)

---

## 3. Kiali API Proxy

### 3.1 Goal

Read-only Kiali API access through Kagenti backend, scoped by RBAC to the user's
allowed namespaces.

### 3.2 Required Backend Work

- **New router**: `kagenti/backend/app/routers/kiali_proxy.py`
- **Endpoints** (under `/api/v1/kiali/`):
  - `GET /graph` — service mesh graph for specified namespaces
  - `GET /namespaces/{ns}/services` — services in a namespace
  - `GET /namespaces/{ns}/workloads` — workloads in a namespace
  - `GET /namespaces/{ns}/apps` — apps in a namespace
  - `GET /health` — Kiali health status
- **Auth**: Kiali API uses OpenShift OAuth. The backend needs a service account token
  or the user's token forwarded.
- **RBAC**: Only return data for namespaces the user has access to (team1, team2, etc.)
  - Configurable via `allowed_namespaces` in platform config
  - Cross-reference with Keycloak roles

### 3.3 Kiali API Reference

Kiali exposes REST API at `<KIALI_URL>/api/`:
- `GET /api/namespaces/{ns}/graph?duration=60s&graphType=workload` — graph data
- `GET /api/namespaces` — list namespaces
- `GET /api/namespaces/{ns}/services` — service list
- `GET /api/namespaces/{ns}/health` — namespace health
- `GET /api/mesh/graph` — full mesh graph

### 3.4 Current State

- Kiali deployed via kagenti-deps Helm chart
- Uses OpenShift OAuth for authentication
- Connected to Istio Ambient mode for traffic data
- `KIALI_URL` is discovered from cluster routes
- Current UI links out to external Kiali dashboard

---

## 4. Custom Graph Visualizations

### 4.1 Goal

Build interactive graph components in the Kagenti UI that visualize trace and mesh
data better than tree views.

### 4.2 Visualization Types

#### 4.2.1 Trace Flow Graph (MLflow data)

- **Input**: Trace spans from MLflow
- **Visualization**: DAG (directed acyclic graph) showing span relationships
- **Nodes**: LLM calls, tool invocations, agent steps
- **Edges**: Parent-child span relationships, timing
- **Attributes**: Color by duration, size by token count, label with model name
- **Interaction**: Click node to see span details, zoom, filter

#### 4.2.2 Agent Interaction Graph (MLflow data)

- **Input**: Multiple traces across agents
- **Visualization**: Network graph showing agent-to-agent communication
- **Nodes**: Agents, tools, external services
- **Edges**: Communication flows, weighted by frequency
- **Attributes**: Color by namespace, size by call frequency

#### 4.2.3 Service Mesh Graph (Kiali data)

- **Input**: Kiali graph API data
- **Visualization**: Network topology showing service-to-service traffic
- **Nodes**: Services, workloads
- **Edges**: HTTP traffic, mTLS status
- **Attributes**: Color by health, animate by traffic volume

#### 4.2.4 Correlated View (MLflow + Kiali)

- **Input**: Combined trace + mesh data
- **Visualization**: Split or overlay view showing:
  - LLM trace spans (what the agent did)
  - Network traffic (how services communicated)
- **Correlation**: Match trace timestamps with mesh traffic windows
- **Value**: See that agent A called tool B, and at the network level, service A
  made HTTP calls to service B through the mesh with mTLS

### 4.3 UI Implementation

#### Library Options

| Library | Pros | Cons |
|---------|------|------|
| **react-flow** | Mature, customizable nodes, fits React | Heavier bundle |
| **vis.js / vis-network** | Lightweight, good for network graphs | Less React-native |
| **d3.js** | Maximum flexibility | Complex, low-level |
| **cytoscape.js** | Graph theory focused, layout algorithms | Steeper learning curve |

**Recommendation**: `react-flow` for DAG/trace graphs, `vis-network` or `cytoscape.js`
for mesh topology.

#### New UI Pages/Components

- `/traces` — New page for custom trace visualization (replaces Phoenix/MLflow links)
- `/mesh` — New page for custom mesh visualization (replaces Kiali link)
- `TraceGraph.tsx` — DAG component for span visualization
- `MeshGraph.tsx` — Network component for service topology
- `CorrelatedView.tsx` — Combined trace + mesh view

### 4.4 React Component Structure

```
src/pages/
├── TracesPage.tsx              # Custom trace visualization page
├── MeshPage.tsx                # Custom mesh visualization page
└── CorrelatedPage.tsx          # Combined view

src/components/
├── TraceGraph/
│   ├── TraceGraph.tsx          # Main DAG component
│   ├── SpanNode.tsx            # Custom node for spans
│   ├── TraceTimeline.tsx       # Timeline sidebar
│   └── SpanDetail.tsx          # Detail panel
├── MeshGraph/
│   ├── MeshGraph.tsx           # Network topology
│   ├── ServiceNode.tsx         # Custom node for services
│   └── TrafficEdge.tsx         # Custom edge with traffic info
└── CorrelatedView/
    ├── CorrelatedView.tsx      # Split/overlay view
    └── TimeRangeSelector.tsx   # Shared time range picker
```

---

## 5. Trace-Mesh Correlation Research

### 5.1 Key Challenge

Correlating LLM traces (from OpenTelemetry) with Istio mesh traffic (from Envoy
proxy metrics) requires matching on:

- **Time**: Trace span timestamps overlap with mesh traffic windows
- **Service**: Trace service name matches mesh workload/service name
- **Namespace**: Both sources tag with Kubernetes namespace

### 5.2 Research Needed

1. **Kiali API graph data format** — What attributes are in the graph response?
   Document the JSON schema for nodes and edges.
2. **MLflow trace span attributes** — What GenAI semantic convention attributes
   are set by the OpenTelemetry instrumentation? See `genai:semantic-conventions` skill.
3. **Timestamp alignment** — Kiali uses Prometheus metrics with configurable time ranges.
   MLflow traces have start/end timestamps. How to align them?
4. **Service name mapping** — Do trace service names match Kiali service names?
   The OTel Collector sets `service.name`; Kiali uses K8s service names.
5. **Network-level detail** — Can we get request-level HTTP data from Kiali, or only
   aggregated metrics? Istio access logs vs Prometheus metrics.

### 5.3 Correlation Strategy

```
MLflow Trace:
  trace_id: abc123
  spans:
    - service: weather-service (ns: team1)
      operation: llm.chat
      start: 2024-01-15T10:00:00Z
      end: 2024-01-15T10:00:05Z
    - service: weather-tool (ns: team1)
      operation: tool.invoke
      start: 2024-01-15T10:00:01Z
      end: 2024-01-15T10:00:03Z

Kiali Graph (team1, last 5m):
  nodes:
    - weather-service (deployment)
    - weather-tool (deployment)
  edges:
    - weather-service → weather-tool (HTTP 200, 50 req/s, mTLS: true)

Correlation:
  "At 10:00:01, weather-service invoked weather-tool (trace span).
   The mesh shows this traffic flowing through Istio with mTLS active."
```

---

## 6. Getting Started

### 6.1 Prerequisites

- HyperShift cluster with Kagenti deployed (use `hypershift:cluster` skill)
- MLflow with traces from agent interactions
- Kiali with mesh traffic visible
- Ask for hosted cluster access first: `/tdd:hypershift`

### 6.2 New Worktree

```bash
# Create worktree for this work
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
git worktree add .worktrees/custom-viz -b feat/custom-visualizations
```

### 6.3 Development Order

1. **Backend first**: MLflow proxy router (simplest, most value)
2. **Frontend**: Basic trace DAG visualization using react-flow
3. **Backend**: Kiali proxy router
4. **Frontend**: Mesh topology visualization
5. **Research**: Trace-mesh correlation approach
6. **Frontend**: Correlated view
7. **Testing**: E2E tests + demo videos for each visualization

### 6.4 TDD Workflow

Use `/tdd:hypershift` for iterative development:
1. Write backend endpoint
2. Test with curl against the cluster
3. Write UI component
4. Test in browser against the cluster
5. Write E2E test
6. Record demo video

---

## 7. Key Files to Reference

| File | Purpose |
|------|---------|
| `kagenti/backend/app/routers/agents.py` | Pattern for new routers |
| `kagenti/backend/app/routers/chat.py` | Streaming response pattern |
| `kagenti/backend/app/main.py` | Router registration |
| `kagenti/ui-v2/src/services/` | API service layer pattern |
| `kagenti/ui-v2/src/pages/ObservabilityPage.tsx` | Current observability page |
| `kagenti/ui-v2/src/App.tsx` | Route registration |
| `charts/kagenti/templates/` | Helm chart for new config |
| `docs/auth/keycloak-patterns.md` | Auth patterns for proxy |
| `.claude/skills/auth/` | Auth setup skills |
| `.claude/skills/genai/` | GenAI semantic conventions |

---

## 8. Environment Variables

The proxy routers will need:

```yaml
# In kagenti-config ConfigMap or backend env
MLFLOW_INTERNAL_URL: "http://mlflow.kagenti-system.svc.cluster.local:5000"
KIALI_INTERNAL_URL: "http://kiali.istio-system.svc.cluster.local:20001"
```

Or discovered from cluster routes/services.

---

## 9. Task Breakdown (for next Claude instance)

| # | Task | Priority | Depends On |
|---|------|----------|------------|
| 1 | Create MLflow proxy router with experiments + traces endpoints | P0 | — |
| 2 | Create MLflow API service in UI (`mlflowService.ts`) | P0 | 1 |
| 3 | Create TraceGraph component with react-flow | P0 | 2 |
| 4 | Create TracesPage with DAG visualization | P0 | 3 |
| 5 | Research Kiali API graph response format | P1 | — |
| 6 | Create Kiali proxy router (read-only, RBAC) | P1 | 5 |
| 7 | Create Kiali API service in UI (`kialiService.ts`) | P1 | 6 |
| 8 | Create MeshGraph component | P1 | 7 |
| 9 | Create MeshPage with topology visualization | P1 | 8 |
| 10 | Research trace-mesh correlation approach | P2 | 5 |
| 11 | Create CorrelatedView component | P2 | 4, 9, 10 |
| 12 | Add new routes to App.tsx and navigation | P0 | 4 |
| 13 | Add Helm chart config for proxy URLs | P1 | 1, 6 |
| 14 | Write E2E tests for new pages | P1 | 4, 9 |
| 15 | Record demo videos for new visualizations | P2 | 14 |

---

## 10. Demo Video Plan

When the custom visualizations are ready, create Playwright demo tests for:

1. **Trace DAG visualization** — Show a trace as an interactive graph
2. **Mesh topology** — Show service mesh with mTLS indicators
3. **Correlated view** — Show trace + mesh side by side
4. **Comparison** — Before (external dashboards) vs after (integrated views)

Add these to `TODO_VIDEOS.md` in the playwright worktree.
