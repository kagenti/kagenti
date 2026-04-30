# Langfuse Cloud Integration for LLM Observability

This document describes how to integrate Kagenti with Langfuse cloud service for LLM trace collection and observability. Langfuse provides traces, evaluations, prompt management, and cost analytics for GenAI applications.

## Overview

Langfuse is a cloud-based LLM observability platform that supports OTLP trace ingestion. Unlike Phoenix and MLflow which can be self-hosted within Kagenti, Langfuse cloud is the recommended approach for Mac M1/ARM64 development environments due to ClickHouse compatibility issues with nested virtualization (Kind/Rancher Desktop on Mac).

## Why Langfuse Cloud?

### Self-Hosted Challenges on Mac M1

Attempts to deploy Langfuse v3 self-hosted on Mac M1 with Kind/Rancher Desktop encountered persistent issues:

**Root Cause**: ClickHouse (Langfuse v3's OLAP database) hangs during startup in nested virtualization environments:
- **Mac M1 → Podman/Lima VM → Kind containers → ClickHouse** = incompatible
- ClickHouse process starts but hangs after "Initialized background executor for common operations"
- Only interserver port (9009) opens; HTTP (8123) and Native (9000) ports never start
- Tested multiple versions (24.3, 24.11, 26.2), configurations, and resource settings - all failed

**Langfuse v3 Requirements**:
- Redis (queue and cache)
- PostgreSQL (transactional data)
- ClickHouse (OLAP for traces/observations)
- MinIO (S3-compatible blob storage)
- Langfuse Web (UI + APIs)
- Langfuse Worker (async event processing)

Managing this 6-container stack with ClickHouse compatibility issues makes self-hosting impractical for local development on Mac M1.

### Langfuse Cloud Solution

**Advantages**:
- ✅ No infrastructure management
- ✅ No ClickHouse deployment issues
- ✅ Works from any cluster (Kind, cloud, OpenShift)
- ✅ Free tier available (Hobby plan, no credit card required)
- ✅ Automatic scaling and high availability
- ✅ Enterprise features available (SSO, SLA, dedicated support)

**Trade-offs**:
- Traces sent to external service (data leaves cluster)
- Requires internet connectivity
- Free tier has usage limits (sufficient for development/testing)
- Production workloads may require paid plans

## Architecture

```
GenAI Agent/Application
    │ OpenTelemetry instrumentation
    │ with GenAI semantic conventions
    ▼
OTEL Collector (kagenti-system)
    │ OTLP receiver (gRPC port 4317, HTTP port 4318)
    │
    ├──► debug exporter (logs)
    │
    └──► otlphttp/langfuse exporter
         │ HTTPS + Basic Auth
         │ compression: gzip
         │ retry & queue
         ▼
Langfuse Cloud (us.cloud.langfuse.com)
    │ stores in managed ClickHouse
    ▼
Langfuse UI (web dashboard)
```

## Prerequisites

- Kagenti platform deployed
- `kubectl` configured and pointing at cluster
- Langfuse cloud account (free tier available)

## Setup Guide

### Step 1: Create Langfuse Cloud Account

1. Go to [Langfuse Cloud](https://us.cloud.langfuse.com) (US region) or [Langfuse EU](https://cloud.langfuse.eu) (EU region)

2. **Sign Up** (free, no credit card required)
   - Use Google/GitHub OAuth or email + password
   - Verify your email

3. **Create a Project**
   - Project name: e.g., "Kagenti Development" or "Kagenti Production"
   - Project description: Optional

### Step 2: Generate API Keys

1. Navigate to **Settings → API Keys**

2. Click **"Create new API key"**

3. Copy both keys (you'll need them in Step 3):
   ```
   Public Key:  pk-lf-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   Secret Key:  sk-lf-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   ```

4. **Important**: Store the Secret Key securely - it won't be shown again

### Step 3: Create Langfuse Values File

Create a Helm values override file for Langfuse configuration:

**File**: `deployments/envs/langfuse-cloud-values.yaml`

```yaml
# Langfuse Cloud OTEL Collector Configuration
# Configures the OTEL collector to export ALL traces to Langfuse cloud service
#
# Usage:
#   helm upgrade kagenti-deps charts/kagenti-deps -n kagenti-system \
#     -f deployments/envs/dev_values.yaml \
#     -f deployments/envs/langfuse-cloud-values.yaml \
#     --set openshift=false

charts:
  kagenti-deps:
    values:
      openshift: false
      components:
        otel:
          enabled: true
      # Override OTEL collector configuration
      otel:
        collector:
          # Add Langfuse exporter to base config
          config:
            exporters:
              debug:
                verbosity: detailed
              otlphttp/langfuse:
                # Langfuse cloud endpoint (US region)
                # For EU region, use: https://cloud.langfuse.eu/api/public/otel
                endpoint: https://us.cloud.langfuse.com/api/public/otel
                headers:
                  # Basic Auth with base64-encoded public_key:secret_key
                  # Generate with: echo -n "pk-lf-...:sk-lf-..." | base64
                  Authorization: "Basic <YOUR_BASE64_ENCODED_KEYS_HERE>"
                compression: gzip
                retry_on_failure:
                  enabled: true
                  initial_interval: 5s
                  max_interval: 30s
                  max_elapsed_time: 300s
                sending_queue:
                  enabled: true
                  num_consumers: 10
                  queue_size: 1000
          # Override defaultConfig to use Langfuse pipeline
          defaultConfig:
            service:
              pipelines:
                traces/langfuse:
                  receivers: [otlp]
                  processors: [memory_limiter, batch]
                  exporters: [debug, otlphttp/langfuse]
```

**Generate Base64 Auth Header**:
```bash
# Replace with your actual keys
echo -n "pk-lf-YOUR-PUBLIC-KEY:sk-lf-YOUR-SECRET-KEY" | base64
```

Copy the output and replace `<YOUR_BASE64_ENCODED_KEYS_HERE>` in the values file.

### Step 4: Deploy/Update Kagenti with Langfuse Configuration

**Option A: New Kagenti Installation**

```bash
cd deployments/ansible

# Deploy with Langfuse configuration
./run-install.sh --env dev \
  --env-file ../envs/langfuse-cloud-values.yaml
```

**Option B: Update Existing Installation**

```bash
# Upgrade the OTEL collector configuration
helm upgrade kagenti-deps charts/kagenti-deps -n kagenti-system \
  -f deployments/envs/dev_values.yaml \
  -f deployments/envs/langfuse-cloud-values.yaml \
  --set openshift=false

# Restart OTEL collector to apply new config
kubectl rollout restart deployment/otel-collector -n kagenti-system

# Wait for OTEL collector to be ready
kubectl wait --for=condition=ready pod -l app=otel-collector -n kagenti-system --timeout=60s
```

### Step 5: Verify Configuration

```bash
# Check OTEL collector configuration includes Langfuse exporter
kubectl get configmap -n kagenti-system otel-collector-config -o yaml | grep -A 5 "langfuse"

# Check OTEL collector logs for startup
kubectl logs -n kagenti-system -l app=otel-collector --tail=50
```

Expected output should show:
- Langfuse exporter configured
- No startup errors
- "Everything is ready. Begin running and processing data."

## Testing the Integration

### Send Test Trace

Create a simple test script to send a GenAI trace:

**File**: `test-langfuse-trace.py`

```python
#!/usr/bin/env python3
"""Send test GenAI trace to verify Langfuse integration"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

# Configure resource
resource = Resource.create({
    "service.name": "langfuse-test",
    "service.version": "1.0.0",
})

# Set up tracer provider
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)

# Configure OTLP exporter to OTEL collector
otlp_exporter = OTLPSpanExporter(
    endpoint="localhost:4317",  # Port-forward to OTEL collector
    insecure=True,
)

# Add batch span processor
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)

print("Sending test GenAI trace to Langfuse...")

# Create span with GenAI semantic conventions
with tracer.start_as_current_span(
    "chat.completions",
    attributes={
        "gen_ai.system": "openai",
        "gen_ai.request.model": "gpt-4",
        "gen_ai.request.temperature": 0.7,
        "gen_ai.usage.input_tokens": 25,
        "gen_ai.usage.output_tokens": 42,
    }
) as span:
    print("✓ Created test span")
    span.set_status(trace.Status(trace.StatusCode.OK))

# Force flush
trace.get_tracer_provider().force_flush()
print("✓ Trace sent to OTEL collector")
print("\nCheck Langfuse UI: https://us.cloud.langfuse.com")
```

**Run the test**:
```bash
# Port-forward OTEL collector
kubectl port-forward -n kagenti-system svc/otel-collector 4317:4317 &

# Install dependencies
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp

# Run test
python3 test-langfuse-trace.py
```

### Verify in Langfuse UI

1. Go to [Langfuse Dashboard](https://us.cloud.langfuse.com)
2. Navigate to **Traces**
3. Look for service: `langfuse-test`
4. Verify trace attributes include:
   - `gen_ai.system`: openai
   - `gen_ai.request.model`: gpt-4
   - Token counts: 25 input, 42 output

## Agent Instrumentation

For Kagenti agents to send traces to Langfuse, they must use:

1. **OpenTelemetry SDK** with OTLP exporter
2. **GenAI semantic conventions** for LLM calls

### Python Agent Example

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

# Configure resource
resource = Resource.create({
    "service.name": "my-agent",
    "service.version": "1.0.0",
})

# Set up tracer provider
trace.set_tracer_provider(TracerProvider(resource=resource))

# Configure OTLP exporter to Kagenti OTEL collector
otlp_exporter = OTLPSpanExporter(
    endpoint="otel-collector.kagenti-system.svc.cluster.local:4317",
    insecure=True,  # Uses Istio mTLS
)

trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)

# Get tracer
tracer = trace.get_tracer(__name__)

# Create spans with GenAI attributes
with tracer.start_as_current_span(
    "llm.call",
    attributes={
        "gen_ai.system": "openai",
        "gen_ai.request.model": "gpt-4o-mini",
        "gen_ai.request.temperature": 0.7,
        "gen_ai.request.max_tokens": 150,
    }
) as span:
    # Make LLM call
    response = openai.chat.completions.create(...)
    
    # Add response attributes
    span.set_attributes({
        "gen_ai.response.model": response.model,
        "gen_ai.usage.input_tokens": response.usage.prompt_tokens,
        "gen_ai.usage.output_tokens": response.usage.completion_tokens,
    })
```

### Auto-Instrumentation (Recommended)

For automatic instrumentation of OpenAI SDK calls:

```bash
# Install auto-instrumentation
pip install opentelemetry-instrumentation-openai

# Enable in your application
from opentelemetry.instrumentation.openai import OpenAIInstrumentor
OpenAIInstrumentor().instrument()
```

This automatically captures all OpenAI SDK calls with proper GenAI semantic conventions.

## GenAI Semantic Conventions

Langfuse requires traces to use [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

### Required Attributes

| Attribute | Type | Description | Example |
|-----------|------|-------------|---------|
| `gen_ai.system` | string | GenAI provider/system | `openai`, `anthropic` |
| `gen_ai.request.model` | string | Model requested | `gpt-4`, `claude-3-opus` |
| `gen_ai.usage.input_tokens` | int | Prompt tokens | `150` |
| `gen_ai.usage.output_tokens` | int | Completion tokens | `250` |

### Optional Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.request.temperature` | float | Sampling temperature |
| `gen_ai.request.max_tokens` | int | Max tokens to generate |
| `gen_ai.request.top_p` | float | Nucleus sampling |
| `gen_ai.response.finish_reasons` | string[] | Why generation stopped |
| `gen_ai.conversation.id` | string | Session/conversation ID |

See [GenAI Semantic Conventions Skill](../.claude/skills/genai:semantic-conventions/SKILL.md) for complete reference.

## Cost Tracking

Langfuse automatically calculates costs based on:
- Model name (`gen_ai.request.model`)
- Token usage (`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`)
- Internal pricing table for various models

**Cost Calculation**:
```
Cost = (input_tokens × input_price) + (output_tokens × output_price)
```

Example for GPT-4:
- Input: $0.03 per 1K tokens
- Output: $0.06 per 1K tokens
- 25 input + 42 output tokens = $0.00327

### View Costs in Langfuse

1. Navigate to **Dashboard**
2. See aggregated costs by:
   - Model
   - User
   - Time period
   - Service/agent

## Langfuse Features

### Traces
- Full request/response traces
- Token usage and costs
- Latency metrics
- Error tracking

### Sessions
- Group related traces
- Track conversation flows
- Multi-turn interactions

### Prompt Management
- Version control for prompts
- A/B testing
- Prompt analytics

### Evaluations
- Custom scoring
- Human feedback
- Model comparisons

### Analytics
- Usage dashboards
- Cost analysis
- Performance metrics
- User analytics

## Troubleshooting

### Traces Not Appearing in Langfuse

**Check OTEL Collector Logs**:
```bash
kubectl logs -n kagenti-system -l app=otel-collector --tail=100
```

Look for errors related to Langfuse exporter.

**Verify Configuration**:
```bash
kubectl get configmap -n kagenti-system otel-collector-config -o yaml
```

Ensure `otlphttp/langfuse` exporter is configured with correct:
- Endpoint URL
- Authorization header (base64-encoded keys)
- Pipeline includes the exporter

**Test Endpoint Manually**:
```bash
# Verify endpoint is accessible (should return auth error, not connection error)
curl -X POST https://us.cloud.langfuse.com/api/public/otel/v1/traces \
  -H "Authorization: Basic YOUR_BASE64_KEY" \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[]}'
```

Expected: HTTP 200 or 401 (not connection error)

### Invalid API Keys

**Symptom**: OTEL collector logs show authentication errors

**Solution**:
1. Verify keys in Langfuse dashboard (Settings → API Keys)
2. Regenerate keys if needed
3. Re-encode as base64: `echo -n "pk-lf-...:sk-lf-..." | base64`
4. Update `langfuse-cloud-values.yaml`
5. Reapply Helm upgrade

### OTEL Collector Not Starting

**Check Pod Status**:
```bash
kubectl get pods -n kagenti-system -l app=otel-collector
kubectl describe pod -n kagenti-system -l app=otel-collector
```

**Common Issues**:
- ConfigMap syntax error (check YAML formatting)
- Invalid exporter configuration
- Missing required fields

### Traces Missing GenAI Attributes

**Symptom**: Traces appear in Langfuse but without model/token information

**Cause**: Agent not using GenAI semantic conventions

**Solution**:
- Ensure agent uses `gen_ai.*` attributes (not `llm.*` or custom attributes)
- Use auto-instrumentation for supported frameworks
- Manually add attributes to spans

## Comparison: Langfuse vs Phoenix

| Feature | Langfuse Cloud | Phoenix (Self-Hosted) |
|---------|----------------|----------------------|
| **Deployment** | Cloud (managed) | In-cluster (Kubernetes) |
| **Setup** | API keys only | Full database + UI deployment |
| **Mac M1 Support** | ✅ Yes | ✅ Yes (no ClickHouse) |
| **Cost** | Free tier + paid plans | Free (infrastructure costs) |
| **Data Location** | External service | In-cluster |
| **Maintenance** | Managed by Langfuse | Self-managed |
| **Trace Format** | GenAI semantic conventions | OpenInference format |
| **Features** | Advanced (prompts, evals, sessions) | Basic (traces, spans) |
| **Scaling** | Automatic | Manual |
| **Internet Required** | Yes | No |

## Pricing

### Free Tier (Hobby Plan)
- ✅ No credit card required
- ✅ Generous limits for development/testing
- ✅ All core features included
- ⚠️ Limited trace volume

### Paid Plans
- Pro: Higher limits, team features
- Team: Advanced collaboration
- Enterprise: SSO, SLA, dedicated support

**Check Usage**: Settings → Usage in Langfuse dashboard

For production deployments, review [Langfuse Pricing](https://langfuse.com/pricing) to ensure limits meet requirements.

## References

- [Langfuse Documentation](https://langfuse.com/docs)
- [Langfuse Cloud](https://us.cloud.langfuse.com)
- [OTLP Integration Guide](https://langfuse.com/docs/integrations/opentelemetry)
- [GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)

## Related Documentation

- [MLflow Integration](./mlflow-integration.md) - Alternative LLM observability
- [Phoenix Deployment](./components.md#phoenix) - Self-hosted observability
- [GenAI Semantic Conventions Skill](../.claude/skills/genai:semantic-conventions/SKILL.md)
- [OTEL Collector Configuration](../charts/kagenti-deps/values.yaml)

## Known Limitations

### ClickHouse Self-Hosting on Mac M1
- Langfuse v3 requires ClickHouse for OTLP ingestion
- ClickHouse incompatible with nested virtualization (Mac M1 + Kind/Rancher)
- Self-hosting works on: native Linux + K8s, cloud K8s (EKS/GKE/OpenShift)
- **Recommended**: Use Langfuse cloud for Mac M1 development

### Multiple Observability Tools
- OTEL collector pipelines can send to multiple exporters simultaneously
- Can configure both Phoenix (OpenInference) and Langfuse (GenAI) pipelines
- Requires careful pipeline configuration to avoid conflicts
- Increases resource usage and complexity

## Feedback

If you encounter issues or have feedback about this integration, please:
1. Check troubleshooting section above
2. Review OTEL collector logs
3. Open an issue in the Kagenti repository with:
   - Deployment environment (Kind/OpenShift/cloud)
   - OTEL collector logs
   - Langfuse dashboard screenshots (if relevant)
