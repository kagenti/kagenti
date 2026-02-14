"""
Minimal OTEL observability setup for any Kagenti agent.

This is ALL the observability code an agent needs (~50 lines).
The OTEL Collector handles MLflow/Phoenix/OpenInference attribute enrichment
via the transform/agent_enrichment processor.

Agent responsibility:
  - TracerProvider + OTLP exporter (standard OTEL boilerplate)
  - Auto-instrumentation for LangChain and OpenAI (one line each)
  - Root span middleware: creates "invoke_agent {name}" span with
    input.value, gen_ai.conversation.id, gen_ai.agent.name,
    gen_ai.operation.name, and output.value

Collector responsibility (transform/agent_enrichment):
  - mlflow.spanInputs, mlflow.spanOutputs, mlflow.traceName, mlflow.source,
    mlflow.version, mlflow.spanType, mlflow.runName, mlflow.user,
    mlflow.trace.session, openinference.span.kind, llm.model_name,
    llm.token_count.*, and all other derived attributes.

Usage:
    from observability_minimal import setup_tracing, setup_auto_instrumentation, create_tracing_middleware

    setup_tracing(service_name="weather-agent", service_version="1.0.0")
    setup_auto_instrumentation()
    app.middleware("http")(create_tracing_middleware(agent_name="weather-agent"))
"""

import json
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

AGENT_NAME = os.getenv("AGENT_NAME", "agent")


def setup_tracing(service_name: str | None = None, service_version: str = "1.0.0"):
    """Initialize TracerProvider with OTLP exporter. Call once at startup."""
    name = service_name or os.getenv("OTEL_SERVICE_NAME", AGENT_NAME)
    resource = Resource({SERVICE_NAME: name, "service.version": service_version})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def setup_auto_instrumentation():
    """Enable LangChain and OpenAI auto-instrumentation. Call once at startup."""
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor

        LangChainInstrumentor().instrument()
    except ImportError:
        pass
    try:
        from opentelemetry.instrumentation.openai import OpenAIInstrumentor

        OpenAIInstrumentor().instrument()
    except ImportError:
        pass


def create_tracing_middleware(agent_name: str | None = None):
    """Return a Starlette/FastAPI middleware that creates the root span."""
    name = agent_name or AGENT_NAME
    tracer = trace.get_tracer("kagenti.agent")

    async def middleware(request, call_next):
        # Skip health/metadata endpoints
        if request.url.path in ("/health", "/ready", "/.well-known/agent-card.json"):
            return await call_next(request)

        # Parse A2A JSON-RPC request body for input and context
        body = await request.body()
        user_input, context_id = "", ""
        try:
            data = json.loads(body)
            parts = data.get("params", {}).get("message", {}).get("parts", [])
            user_input = parts[0].get("text", "") if parts else ""
            context_id = data.get("params", {}).get("contextId", "")
        except Exception:
            pass

        with tracer.start_as_current_span(f"invoke_agent {name}") as span:
            span.set_attribute("gen_ai.agent.name", name)
            span.set_attribute("gen_ai.operation.name", "invoke_agent")
            if user_input:
                span.set_attribute("input.value", user_input[:4096])
            if context_id:
                span.set_attribute("gen_ai.conversation.id", context_id)

            response = await call_next(request)

            # Capture output for non-streaming responses
            if hasattr(response, "body"):
                try:
                    resp_data = json.loads(response.body)
                    parts = (
                        resp_data.get("result", {})
                        .get("artifacts", [{}])[0]
                        .get("parts", [])
                    )
                    output = parts[0].get("text", "") if parts else ""
                    if output:
                        span.set_attribute("output.value", output[:4096])
                except Exception:
                    pass

            return response

    return middleware
