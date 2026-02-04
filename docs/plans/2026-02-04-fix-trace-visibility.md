# Fix Trace Visibility in Phoenix and MLflow

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix broken trace display in MLflow UI (empty columns) and ensure proper trace hierarchy in both Phoenix and MLflow.

**Architecture:** The current approach manually breaks the trace chain and creates a new root span, but this causes issues with MLflow column population. The older approach in PR #105 (agent-examples) uses a proper `observability.py` module with `using_attributes` context manager and `create_agent_span` helper that wraps the entire execution, creating proper parent spans with OpenInference semantic conventions. We'll port this approach while keeping the OTEL Collector transforms for MLflow.

**Tech Stack:** OpenTelemetry, OpenInference, LangChain Instrumentation, OTEL Collector transform processor

---

## Background Analysis

### Current State (Broken)

The `genai-autoinstrumentation` branch in agent-examples manually breaks the trace chain:

```python
# Creates empty context to break A2A trace chain
empty_ctx = otel_context.Context()
detach_token = otel_context.attach(empty_ctx)

# Creates span with no parent
span = tracer.start_span("gen_ai.agent.invoke", ...)
```

**Problems:**
1. Manual context manipulation is fragile
2. LangChain spans inside aren't getting `session.id`, `user.id` attributes
3. MLflow UI columns remain empty because:
   - `input.value` / `output.value` are on a manually created span
   - The span hierarchy doesn't match what MLflow expects
   - Token counts from OpenAI instrumentation are on nested spans, not propagated up

### Better Approach (PR #105)

PR #105 introduces a proper `observability.py` module with:

1. **`setup_observability()`** - Sets up tracer provider with OpenInference instrumentation
2. **`using_attributes`** context manager - Adds `session.id`, `user.id` to ALL spans in scope
3. **`create_agent_span`** - Creates a root AGENT span with proper OpenInference attributes
4. **W3C Trace Context propagation** - Handles `traceparent` header for distributed tracing

### Key Insight

The issue is that:
- MLflow reads `mlflow.spanInputs` / `mlflow.spanOutputs` from the **root span** of a trace
- Currently, the root span is an A2A framework span (filtered out) or our manually created span
- We need to ensure the AGENT span IS the root span AND has the right attributes

---

## Task Overview

| Task | Description | Files |
|------|-------------|-------|
| 1 | Port observability.py from PR #105 | agent-examples |
| 2 | Update agent.py to use new observability | agent-examples |
| 3 | Verify OTEL Collector transforms | mlflow-ci |
| 4 | Update E2E tests for column validation | mlflow-ci |
| 5 | Deploy and verify on cluster | - |

---

## Task 1: Port observability.py Module

**Files:**
- Create: `.worktrees/agent-examples/a2a/weather_service/src/weather_service/observability.py`
- Modify: `.worktrees/agent-examples/a2a/weather_service/pyproject.toml`

### Step 1.1: Check current pyproject.toml dependencies

Review current dependencies to see what's already there.

Run: `cat .worktrees/agent-examples/a2a/weather_service/pyproject.toml`

### Step 1.2: Create observability.py

Create the observability module based on PR #105, but simplified:

```python
"""
OpenTelemetry observability setup for Weather Agent.

Key Features:
- Auto-instrumentation of LangChain with OpenInference
- `create_agent_span` for creating root AGENT spans
- W3C Trace Context propagation for distributed tracing
"""

import logging
import os
from typing import Dict, Any, Optional
from contextlib import contextmanager
from opentelemetry import trace, context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status, StatusCode
from opentelemetry.propagate import set_global_textmap, extract
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator

logger = logging.getLogger(__name__)

# OpenInference semantic conventions
try:
    from openinference.semconv.trace import SpanAttributes, OpenInferenceSpanKindValues
    OPENINFERENCE_AVAILABLE = True
except ImportError:
    OPENINFERENCE_AVAILABLE = False
    logger.warning("openinference-semantic-conventions not available")


def _get_otlp_exporter(endpoint: str):
    """Get HTTP OTLP exporter."""
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    if not endpoint.endswith("/v1/traces"):
        endpoint = endpoint.rstrip("/") + "/v1/traces"
    return OTLPSpanExporter(endpoint=endpoint)


def setup_observability() -> None:
    """
    Set up OpenTelemetry tracing with OpenInference instrumentation.

    Call this ONCE at agent startup, before importing agent code.
    """
    service_name = os.getenv("OTEL_SERVICE_NAME", "weather-service")
    namespace = os.getenv("K8S_NAMESPACE_NAME", "team1")
    otlp_endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://otel-collector.kagenti-system.svc.cluster.local:8335"
    )

    logger.info("=" * 60)
    logger.info("Setting up OpenTelemetry observability")
    logger.info(f"  Service: {service_name}")
    logger.info(f"  Namespace: {namespace}")
    logger.info(f"  OTLP Endpoint: {otlp_endpoint}")
    logger.info("=" * 60)

    # Create resource with service attributes
    resource = Resource(attributes={
        "service.name": service_name,
        "service.namespace": namespace,
        "k8s.namespace.name": namespace,
    })

    # Create and configure tracer provider
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(_get_otlp_exporter(otlp_endpoint))
    )
    trace.set_tracer_provider(tracer_provider)

    # Auto-instrument LangChain with OpenInference
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
        LangChainInstrumentor().instrument()
        logger.info("✅ LangChain instrumented with OpenInference")
    except ImportError:
        logger.warning("openinference-instrumentation-langchain not available")

    # Configure W3C Trace Context propagation
    set_global_textmap(CompositePropagator([
        TraceContextTextMapPropagator(),
        W3CBaggagePropagator(),
    ]))

    # Instrument OpenAI for GenAI semantic conventions
    try:
        from opentelemetry.instrumentation.openai import OpenAIInstrumentor
        OpenAIInstrumentor().instrument()
        logger.info("✅ OpenAI instrumented with GenAI semantic conventions")
    except ImportError:
        logger.warning("opentelemetry-instrumentation-openai not available")


# Tracer for manual spans - use OpenInference-compatible name
_tracer: Optional[trace.Tracer] = None
TRACER_NAME = "openinference.instrumentation.agent"


def get_tracer() -> trace.Tracer:
    """Get tracer for creating manual spans."""
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer(TRACER_NAME)
    return _tracer


@contextmanager
def create_agent_span(
    name: str = "gen_ai.agent.invoke",
    context_id: Optional[str] = None,
    task_id: Optional[str] = None,
    user_id: Optional[str] = None,
    input_text: Optional[str] = None,
    break_parent_chain: bool = True,
):
    """
    Create an AGENT span that serves as root for LangChain spans.

    Args:
        name: Span name (use gen_ai.agent.* for MLflow AGENT type detection)
        context_id: A2A context_id (becomes gen_ai.conversation.id)
        task_id: A2A task_id
        user_id: User identifier
        input_text: User input message
        break_parent_chain: If True, creates a new root span (breaks A2A chain)

    Yields:
        The span object (set output.value on it before exiting)
    """
    tracer = get_tracer()

    # Build attributes
    attributes = {}

    # GenAI semantic conventions (for OTEL Collector transforms)
    if context_id:
        attributes["gen_ai.conversation.id"] = context_id
    if input_text:
        attributes["gen_ai.prompt"] = input_text[:1000]
        attributes["input.value"] = input_text[:1000]
    attributes["gen_ai.agent.name"] = "weather-assistant"
    attributes["gen_ai.system"] = "langchain"

    # OpenInference span kind
    if OPENINFERENCE_AVAILABLE:
        attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND] = OpenInferenceSpanKindValues.AGENT.value

    # Custom attributes for debugging
    if task_id:
        attributes["a2a.task_id"] = task_id
    if user_id:
        attributes["user.id"] = user_id

    # Break the parent chain if requested
    # This makes our span the root, so MLflow sees our attributes
    parent_context = None
    detach_token = None

    if break_parent_chain:
        # Store current span for linking
        current_span = trace.get_current_span()
        if current_span and current_span.get_span_context().is_valid:
            from opentelemetry.trace import Link
            attributes["_parent_links"] = [Link(current_span.get_span_context())]

        # Create empty context to break chain
        empty_ctx = context.Context()
        detach_token = context.attach(empty_ctx)

    # Start the span
    with tracer.start_as_current_span(name, attributes=attributes) as span:
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
        finally:
            if detach_token:
                context.detach(detach_token)


@contextmanager
def trace_context_from_headers(headers: Dict[str, str]):
    """
    Activate trace context from HTTP headers.

    Use this to connect to incoming distributed trace.
    """
    ctx = extract(headers)
    token = context.attach(ctx)
    try:
        yield ctx
    finally:
        context.detach(token)
```

### Step 1.3: Update pyproject.toml if needed

Ensure dependencies include:
- `openinference-semantic-conventions>=0.1.0`
- `openinference-instrumentation-langchain>=0.1.36`

### Step 1.4: Commit observability module

```bash
cd .worktrees/agent-examples
git add a2a/weather_service/src/weather_service/observability.py
git add a2a/weather_service/pyproject.toml
git commit -s -m "feat(weather): add observability module for proper trace setup

- Add setup_observability() for one-time tracer initialization
- Add create_agent_span() context manager for AGENT spans
- Support breaking parent chain for clean trace roots
- Configure W3C Trace Context propagation"
```

---

## Task 2: Update agent.py to Use Observability Module

**Files:**
- Modify: `.worktrees/agent-examples/a2a/weather_service/src/weather_service/__init__.py`
- Modify: `.worktrees/agent-examples/a2a/weather_service/src/weather_service/agent.py`

### Step 2.1: Update __init__.py to call setup

```python
"""Weather Service - OpenTelemetry Observability Setup"""

from weather_service.observability import setup_observability

# Initialize observability before importing agent
setup_observability()
```

### Step 2.2: Simplify agent.py

Replace the manual context manipulation with `create_agent_span`:

```python
# In execute() method, replace the manual span code with:

from weather_service.observability import create_agent_span

# Inside execute():
user_input = context.get_user_input()

with create_agent_span(
    name="gen_ai.agent.invoke",
    context_id=task.context_id,
    task_id=task.id,
    input_text=user_input,
    break_parent_chain=True,
) as span:
    # ... existing graph execution code ...

    # At the end, set output on span
    if output:
        span.set_attribute("gen_ai.completion", str(output)[:1000])
        span.set_attribute("output.value", str(output)[:1000])
```

### Step 2.3: Run local test

```bash
cd .worktrees/agent-examples/a2a/weather_service
uv sync
uv run python -c "from weather_service import *; print('Import OK')"
```

Expected: No import errors, observability setup logs printed

### Step 2.4: Commit agent changes

```bash
git add a2a/weather_service/src/weather_service/__init__.py
git add a2a/weather_service/src/weather_service/agent.py
git commit -s -m "refactor(weather): use observability module for trace setup

- Move tracer setup to observability module
- Use create_agent_span() for clean AGENT spans
- Remove manual context manipulation
- Simplify execute() method"
```

---

## Task 3: Verify OTEL Collector Transforms

**Files:**
- Review: `.worktrees/mlflow-ci/charts/kagenti-deps/templates/otel-collector.yaml`

### Step 3.1: Verify transform/genai_to_mlflow exists

The OTEL Collector should have transforms that map:

| Source Attribute | Target Attribute | MLflow UI Column |
|------------------|------------------|------------------|
| `input.value` | `mlflow.spanInputs` | Request |
| `output.value` | `mlflow.spanOutputs` | Response |
| `gen_ai.conversation.id` | `mlflow.trace.session` | Session |
| `gen_ai.agent.name` | `mlflow.traceName` | Trace name |
| `service.name` | `mlflow.user` | User |
| (static) | `mlflow.source` | Source |

Check: These transforms exist in the current otel-collector.yaml (verified in analysis).

### Step 3.2: Verify filter/mlflow excludes A2A spans

The filter should exclude spans matching `^a2a\..*` - this is present.

### Step 3.3: Verify pipeline configuration

Pipeline should be:
```yaml
traces/mlflow:
  receivers: [ otlp ]
  processors: [ memory_limiter, filter/mlflow, transform/genai_to_mlflow, batch ]
  exporters: [ debug, otlphttp/mlflow ]
```

This is already correct in the mlflow-ci worktree.

**No changes needed to OTEL Collector config.**

---

## Task 4: Add E2E Test for MLflow Column Validation

**Files:**
- Modify: `.worktrees/mlflow-ci/kagenti/tests/e2e/common/test_mlflow_traces.py`

### Step 4.1: Add test for MLflow UI columns

Add a test that validates the trace metadata fields are populated:

```python
@pytest.mark.observability
class TestMLflowUIColumns:
    """Tests that MLflow UI columns are populated from agent traces."""

    def test_trace_has_request_response(self, mlflow_client, conversation_trace):
        """Verify Request and Response columns have content."""
        # Get root span
        root_span = conversation_trace.spans[0]

        # Check for input (Request column)
        assert any(
            attr.key in ("mlflow.spanInputs", "input.value", "gen_ai.prompt")
            for attr in root_span.attributes
        ), f"Root span missing input attributes: {[a.key for a in root_span.attributes]}"

        # Check for output (Response column)
        assert any(
            attr.key in ("mlflow.spanOutputs", "output.value", "gen_ai.completion")
            for attr in root_span.attributes
        ), f"Root span missing output attributes: {[a.key for a in root_span.attributes]}"

    def test_trace_has_session(self, mlflow_client, conversation_trace):
        """Verify Session column is populated."""
        # Session comes from resource attributes
        session = conversation_trace.metadata.get("session")
        assert session is not None, "Trace missing session metadata"

    def test_trace_has_name(self, mlflow_client, conversation_trace):
        """Verify Trace name column is populated."""
        trace_name = conversation_trace.metadata.get("name")
        assert trace_name is not None, "Trace missing name metadata"
```

### Step 4.2: Run tests locally (skip if no cluster)

```bash
cd .worktrees/mlflow-ci/kagenti
uv run pytest tests/e2e/common/test_mlflow_traces.py -v -k "test_trace" --collect-only
```

### Step 4.3: Commit test updates

```bash
git add kagenti/tests/e2e/common/test_mlflow_traces.py
git commit -s -m "test(e2e): add MLflow UI column validation tests

- Add tests for Request/Response column population
- Add tests for Session and Trace name columns
- Validate root span has required attributes"
```

---

## Task 5: Deploy and Verify on Cluster

**IMPORTANT:** Use inline `KUBECONFIG=...` for all kubectl commands (export doesn't persist between shell sessions).

### Cluster Details

- **Cluster:** kagenti-hypershift-custom-mlflow
- **Kubeconfig:** `~/clusters/hcp/kagenti-hypershift-custom-mlflow/auth/kubeconfig`
- **MLflow URL:** `https://mlflow-kagenti-system.apps.kagenti-hypershift-custom-mlflow.octo-emerging.redhataicoe.com`
- **Phoenix URL:** `https://phoenix-kagenti-system.apps.kagenti-hypershift-custom-mlflow.octo-emerging.redhataicoe.com`

### Step 5.1: Verify cluster access

```bash
# Test cluster connectivity
KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-mlflow/auth/kubeconfig kubectl cluster-info

# Check pods are running
KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-mlflow/auth/kubeconfig kubectl get pods -n kagenti-system | head -15
```

### Step 5.2: Trigger weather agent rebuild

```bash
# Create BuildRun to rebuild weather-service with new code
KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-mlflow/auth/kubeconfig kubectl create -f - <<EOF
apiVersion: shipwright.io/v1beta1
kind: BuildRun
metadata:
  generateName: weather-service-observability-
  namespace: team1
spec:
  build:
    name: weather-service
EOF

# Watch build progress
KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-mlflow/auth/kubeconfig kubectl get buildrun -n team1 -w
```

### Step 5.3: Generate test traces

Use the `local:full-test` skill to run tests:

```bash
# Invoke skill: local:full-test
# Filter: test_agent
# Cluster: mlflow (already deployed)
```

Or manually:
```bash
KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-mlflow/auth/kubeconfig \
  ./.github/scripts/local-setup/hypershift-full-test.sh mlflow \
  --include-test --pytest-filter "test_agent"
```

### Step 5.4: Verify MLflow UI

1. Open MLflow UI: `https://mlflow-kagenti-system.apps.kagenti-hypershift-custom-mlflow.octo-emerging.redhataicoe.com`
2. Navigate to Traces tab
3. Check columns are populated:
   - **Request**: Shows user message
   - **Response**: Shows agent response
   - **Session**: Shows context_id
   - **Trace name**: Shows agent name

### Step 5.5: Run MLflow-specific E2E tests

Use the `local:full-test` skill:

```bash
# Invoke skill: local:full-test
# Filter: test_mlflow
# Cluster: mlflow
```

Or manually:
```bash
KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-mlflow/auth/kubeconfig \
  ./.github/scripts/local-setup/hypershift-full-test.sh mlflow \
  --include-test --pytest-filter "test_mlflow"
```

---

## PR #105 Integration Decision

### Do We Need Baggage?

**Current answer: No, not yet.**

Baggage propagation is useful for:
- Passing user_id, tenant_id across service boundaries
- Multi-hop tracing with context

For now, we're setting these directly on spans. We can add baggage later if:
- We need to pass context through the MCP tool call
- We implement multi-agent orchestration

The `observability.py` module from PR #105 includes baggage helpers, but we can omit them initially for simplicity.

### What to Port from PR #105

1. ✅ `setup_observability()` - tracer setup with OpenInference
2. ✅ `create_agent_span()` - context manager for AGENT spans
3. ✅ `trace_context_from_headers()` - for distributed tracing
4. ⏸️ Baggage utilities - defer until needed
5. ⏸️ `using_attributes` wrapper - OpenInference handles this via LangChainInstrumentor

---

## Success Criteria

| Criterion | Validation |
|-----------|------------|
| MLflow Request column populated | Shows user message in UI |
| MLflow Response column populated | Shows agent response in UI |
| MLflow Session column populated | Shows context_id UUID |
| MLflow Trace name populated | Shows "weather-assistant" or span name |
| Phoenix receives traces | Traces visible in Phoenix UI |
| E2E tests pass | `test_mlflow_traces.py` all green |

---

## Rollback Plan

If issues arise:
1. Revert agent-examples to previous commit
2. Keep OTEL Collector transforms (they're harmless without agent changes)
3. Investigate specific failure in OTEL Collector debug logs

---

## References

- PR #569: https://github.com/kagenti/kagenti/pull/569
- PR #105: https://github.com/kagenti/agent-examples/pull/105
- MLflow OTEL Support: https://mlflow.org/docs/latest/genai/tracing/opentelemetry/ingest/
- OpenInference Spec: https://github.com/Arize-ai/openinference
- GenAI Semantic Conventions: https://opentelemetry.io/docs/specs/semconv/gen-ai/
