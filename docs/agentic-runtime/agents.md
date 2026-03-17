# Writing Agents

This guide covers how to write a sandbox agent for the Kagenti Agentic Runtime.

---

## Architecture

Every sandbox agent runs as an A2A (Agent-to-Agent) service inside a
Kubernetes pod. The platform provides infrastructure layers (auth, security,
workspace, budget) while the agent provides business logic.

```
+-----------------------------------------------+
|  Platform Base (entrypoint.py)                 |
|  - Plugin loading (AGENT_MODULE env var)       |
|  - WorkspaceManager (per-context isolation)    |
|  - PermissionChecker (ALLOW/DENY/HITL)         |
|  - SourcesConfig (capabilities)                |
|  - A2A server (Starlette + Uvicorn)            |
+-----------------------------------------------+
|  Agent Plugin (your code)                      |
|  - get_agent_card() -> AgentCard               |
|  - build_executor() -> AgentExecutor           |
+-----------------------------------------------+
```

## Plugin Contract

Every agent framework adapter must export two functions:

### `get_agent_card(host, port) -> AgentCard`

Returns A2A metadata describing your agent:

```python
from a2a.types import AgentCard, AgentCapabilities, AgentSkill

def get_agent_card(host: str, port: int) -> AgentCard:
    return AgentCard(
        name="My Agent",
        description="A coding agent that does X",
        version="1.0.0",
        url=f"http://{host}:{port}/",
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="my_skill",
                name="My Skill",
                description="What this agent does",
                tags=["coding", "shell"],
            )
        ],
    )
```

### `build_executor(workspace_manager, permission_checker, sources_config) -> AgentExecutor`

Returns an executor that handles requests with platform services injected:

```python
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

def build_executor(workspace_manager, permission_checker, sources_config, **kwargs):
    return MyExecutor(workspace_manager, permission_checker, sources_config)

class MyExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_input = context.get_user_input()
        context_id = context.current_task.context_id

        # 1. Resolve workspace
        workspace = self._workspace_manager.ensure_workspace(context_id)

        # 2. Run your agent logic
        result = await self._run_agent(user_input, workspace)

        # 3. Emit A2A events
        task_updater = TaskUpdater(event_queue, context.current_task.id, context_id)
        await task_updater.update_status(TaskState.working, ...)
        await task_updater.add_artifact([TextPart(text=result)])
        await task_updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass  # Optional: handle cancellation
```

## Instrumentation Contract

Beyond the plugin contract, agents should implement two instrumentation
components to enable the full UI experience (graph views, event persistence):

### FrameworkEventSerializer

Translates your framework's native events into the universal EVENT_CATALOG
format (see [Concepts](./concepts.md#event-categories)):

```python
from abc import ABC, abstractmethod

class FrameworkEventSerializer(ABC):
    @abstractmethod
    def serialize(self, key: str, value: dict) -> str:
        """Translate a framework event into EVENT_CATALOG JSON line(s).

        Args:
            key: Framework-specific event identifier
            value: Event payload

        Returns:
            Newline-delimited JSON. Each line must include {"type": "..."}
        """
```

Each JSON line must include the common event fields:

| Field | Type | Required |
|-------|------|----------|
| `type` | string | Yes -- event type from catalog |
| `loop_id` | string | Yes -- unique per reasoning loop invocation |
| `langgraph_node` | string | Yes -- logical processing stage name |
| `node_visit` | int | Yes -- monotonic counter |
| `event_index` | int | Yes -- global sequence number |
| `model` | string | If LLM call |
| `prompt_tokens` | int | If LLM call |
| `completion_tokens` | int | If LLM call |

### AgentGraphCard

Expose a graph card at `/.well-known/agent-graph-card.json` describing your
agent's event catalog and graph topology:

```python
def build_graph_card(compiled_graph, agent_id="my_agent"):
    return {
        "id": agent_id,
        "framework": "my_framework",
        "version": "1.0",
        "event_catalog": {
            "planner_output": {
                "category": "reasoning",
                "description": "Agent created a plan",
                "has_llm_call": True,
                "fields": {"steps": "List[str]"},
            },
            "tool_call": {
                "category": "execution",
                "description": "Tool invoked",
                "has_llm_call": False,
                "fields": {"name": "str", "args": "str"},
            },
            # ... other event types
        },
        "common_event_fields": { ... },
        "topology": {
            "nodes": {
                "planner": "Creates plan from user request",
                "executor": "Runs tools",
                "reporter": "Final answer",
            },
            "edges": [
                {"source": "__start__", "target": "planner"},
                {"source": "planner", "target": "executor"},
                {"source": "executor", "target": "reporter"},
                {"source": "reporter", "target": "__end__"},
            ],
            "entry_node": "planner",
        },
    }
```

The LangGraph reference implementation introspects the compiled graph
programmatically via `compiled_graph.get_graph()`. For simpler frameworks
(ReAct loops), a static topology is sufficient.

## Dockerfile

Agents are built on the platform base image:

```dockerfile
FROM kagenti-agent-base:latest

# Install your framework
RUN pip install my-framework

# Copy your agent code
COPY agents/my_agent/ /app/my_agent/

# Set the plugin module
ENV AGENT_MODULE=my_agent.plugin

# Platform base entrypoint handles everything else
CMD ["python", "-m", "platform_base.entrypoint"]
```

The base image provides:
- Python 3.12-slim
- Platform base modules (workspace, permissions, sources, entrypoint)
- A2A SDK
- `/workspace` directory
- Non-root user (UID 1001)

## Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-agent
  namespace: team1
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: agent
          image: my-agent:latest
          ports:
            - containerPort: 8000
          env:
            - name: AGENT_MODULE
              value: my_agent.plugin
            - name: LLM_API_BASE
              value: http://llm-budget-proxy:8080
            - name: LLM_MODEL
              value: llama-4-scout-17b
            - name: TASK_STORE_DB_URL
              valueFrom:
                secretKeyRef:
                  name: postgres-sessions-secret
                  key: connection-string
          volumeMounts:
            - name: workspace
              mountPath: /workspace
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            capabilities:
              drop: [ALL]
      volumes:
        - name: workspace
          emptyDir:
            sizeLimit: 5Gi
```

## Reference: LangGraph Agent Structure

The reference sandbox agent (`a2a/sandbox_agent/`) demonstrates the full
implementation:

```
sandbox_agent/
├── agent.py              # A2A server entry point
├── graph.py              # LangGraph state & graph builder
├── reasoning.py          # Plan-execute-reflect nodes (1700+ lines)
├── executor.py           # Shell execution with permission checks
├── permissions.py        # Permission validator
├── budget.py             # Token/iteration/time limits
├── event_serializer.py   # LangGraph -> EVENT_CATALOG (697 lines)
├── event_schema.py       # Event type definitions
├── graph_card.py         # AgentGraphCard builder (580 lines)
├── observability.py      # OpenTelemetry setup
├── workspace.py          # Per-context workspace manager
├── landlock_ctypes.py    # Landlock LSM wrapper (193 lines)
├── landlock_probe.py     # Kernel capability probe
├── subagents.py          # Explore & delegate tools
├── plan_store.py         # Plan persistence
├── prompts.py            # System prompts
└── sources.py            # Configuration
```

See the [Multi-Framework Runtime](./multi-framework.md) guide for adapting
other frameworks.
