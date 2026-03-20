# HITL Proper Implementation + Pod Events Tab — Design

> **Date:** 2026-03-12
> **Status:** Designed
> **PR:** #758 (feat/sandbox-agent)

---

## Part 1: HITL Proper Implementation

### Problem

When the permission checker triggers HITL (e.g., interpreter bypass for
`python3 -c`), the agent calls `interrupt()` which suspends the LangGraph
graph. But the A2A event loop ends and `task_updater.complete()` marks the
task as `completed` with `"No response generated."` — losing all work done
so far and leaving the user with no way to approve/deny.

### Root Cause

Six code locations need changes:

### 1. Permission Result with Rule Details

**File:** `sandbox_agent/permissions.py`

Currently `check()` returns a bare enum. Add rule details:

```python
@dataclass
class PermissionCheckResult:
    decision: PermissionResult  # ALLOW, DENY, HITL
    rule: str | None = None     # e.g. "interpreter_bypass(python3 -c)"
    reason: str | None = None   # e.g. "Pipe to interpreter with -c flag"
```

Update `check()`, `_check_single()`, `_check_compound()` to return
`PermissionCheckResult` instead of `PermissionResult`.

Interpreter bypass (line 114) returns:
```python
return PermissionCheckResult(
    PermissionResult.HITL,
    rule="interpreter_bypass",
    reason=f"Pipe to {cmd} with {flag} flag executes arbitrary code",
)
```

No-match HITL (line 119) returns:
```python
return PermissionCheckResult(
    PermissionResult.HITL,
    rule="no_matching_rule",
    reason=f"No allow rule matches {operation_type}({operation[:80]})",
)
```

### 2. HitlRequired Exception with Rule

**File:** `sandbox_agent/executor.py`

Add `rule` and `reason` fields to `HitlRequired`:

```python
class HitlRequired(Exception):
    def __init__(self, command: str, rule: str = "", reason: str = ""):
        self.command = command
        self.rule = rule
        self.reason = reason
```

### 3. Interrupt Payload with Rule

**File:** `sandbox_agent/graph.py` (line 258)

Pass rule details into the interrupt payload:

```python
approval = interrupt({
    "type": "approval_required",
    "command": exc.command,
    "rule": exc.rule,
    "reason": exc.reason,
    "message": f"Command '{exc.command}' requires human approval.",
})
```

### 4. Agent Detects HITL and Sets input_required

**File:** `sandbox_agent/agent.py` (after event loop, line ~624)

Track whether the graph was interrupted:

```python
hitl_interrupted = False

# In the event loop (line 509):
if "__interrupt__" in event:
    hitl_interrupted = True
    # ... existing hitl_request emission ...

# After event loop (line ~624):
if hitl_interrupted:
    # Don't mark as completed — task is waiting for human input
    await task_updater.update_status(
        TaskState.input_required,
        new_agent_text_message(
            json.dumps({"type": "hitl_waiting", "message": "Waiting for human approval"}),
            task_updater.context_id,
            task_updater.task_id,
        ),
    )
    return  # Don't call complete()
```

### 5. HITL Resume Handler

**File:** `sandbox_agent/agent.py`

When a new message arrives for a task in `input_required` state, resume
the suspended graph:

```python
# In execute():
if existing_task and existing_task.status.state == TaskState.input_required:
    # Resume graph with approval
    from langgraph.types import Command
    result = await compiled_graph.ainvoke(
        Command(resume={"approved": True}),
        config={"configurable": {"thread_id": context_id}},
    )
    # Continue with normal event processing...
```

For deny: resume with `{"approved": False}` — the graph.py handler at
line 264-267 returns a DENIED message and continues.

### 6. Backend Approve/Deny Endpoints

**File:** `kagenti/backend/app/routers/sandbox.py`

The existing stubs need to forward to the agent:

```python
@router.post("/{namespace}/sessions/{context_id}/approve")
async def approve_hitl(namespace: str, context_id: str):
    # Send a message to the agent with approval payload
    # The agent's execute() detects input_required and resumes graph
    agent_url = get_agent_url(namespace, context_id)
    await send_a2a_message(agent_url, context_id, "APPROVED")

@router.post("/{namespace}/sessions/{context_id}/deny")
async def deny_hitl(namespace: str, context_id: str):
    await send_a2a_message(agent_url, context_id, "DENIED")
```

### UI Changes

**AgentLoopCard** — when loop receives `hitl_request` event:

- Show the command that needs approval in a highlighted box
- Show the **rule breached** (e.g., "Interpreter bypass: `python3 -c`")
- Show the **reason** (e.g., "Pipe to interpreter executes arbitrary code")
- Approve / Deny buttons
- On approve: `POST /api/v1/sandbox/{ns}/sessions/{ctx}/approve`
- On deny: `POST /api/v1/sandbox/{ns}/sessions/{ctx}/deny`
- After approve: loop resumes, new events stream in

### Event Flow (Fixed)

```
1. Agent calls shell("cat ... | python3 -c ...")
2. permissions.check() -> HITL (interpreter_bypass, "python3 -c")
3. executor raises HitlRequired(command, rule, reason)
4. graph.py: interrupt({type, command, rule, reason, message})
5. LangGraph suspends graph (checkpoint saved)
6. agent.py: emits hitl_request event with rule + reason
7. agent.py: detects hitl_interrupted, sets task to input_required
8. UI: shows HITL card with rule, reason, Approve/Deny buttons
9. User clicks Approve
10. Backend: POST /approve -> sends message to agent
11. agent.py: detects input_required, resumes graph with Command(resume=approved)
12. graph.py: interrupt() returns {approved: True}, executes command
13. Loop continues with tool result
```

---

## Part 2: Pod Events Tab

### Problem

When agents crash (OOM, restarts, evictions), the only way to know is
`kubectl describe pod` or `kubectl get events`. The UI has no visibility
into pod-level health.

### Design

Add a **Pod** tab alongside Chat, Stats, LLM Usage, Files:

```
[Chat] [Stats] [LLM Usage] [Files] [Pod]
```

### Backend Endpoint

```
GET /api/v1/sandbox/{namespace}/agents/{agent_name}/pod-status
```

Returns:
```json
{
  "pod_name": "sandbox-legion-87dcf4d9-s8wzm",
  "status": "Running",
  "restarts": 6,
  "last_restart_reason": "OOMKilled",
  "last_restart_time": "2026-03-12T15:28:05Z",
  "containers": [{
    "name": "agent",
    "state": "running",
    "ready": true,
    "restart_count": 6,
    "last_state": {
      "terminated": {
        "reason": "OOMKilled",
        "exit_code": 137,
        "started_at": "2026-03-12T15:26:15Z",
        "finished_at": "2026-03-12T15:28:05Z"
      }
    },
    "resources": {
      "requests": {"cpu": "100m", "memory": "256Mi"},
      "limits": {"cpu": "500m", "memory": "512Mi"}
    }
  }],
  "events": [
    {
      "type": "Warning",
      "reason": "OOMKilling",
      "message": "Memory cgroup out of memory: Killed process 1234",
      "first_seen": "2026-03-12T15:28:05Z",
      "count": 6
    },
    {
      "type": "Normal",
      "reason": "Pulled",
      "message": "Container image pulled",
      "first_seen": "2026-03-12T15:28:10Z",
      "count": 7
    }
  ],
  "node": "ip-10-0-132-176.ec2.internal"
}
```

### Backend Implementation

```python
@router.get("/{namespace}/agents/{agent_name}/pod-status")
async def get_pod_status(namespace: str, agent_name: str):
    core_v1 = kubernetes.client.CoreV1Api()

    # Get pods for this agent
    pods = core_v1.list_namespaced_pod(
        namespace,
        label_selector=f"app.kubernetes.io/name={agent_name}"
    )

    # Get events for the pod
    events = core_v1.list_namespaced_event(
        namespace,
        field_selector=f"involvedObject.name={pod.metadata.name}"
    )

    # Build response from pod status + events
    ...
```

### UI Component

**PodStatusPanel.tsx** — renders in the Pod tab:

- **Status bar:** Pod name, status badge (Running/CrashLoopBackOff/OOMKilled),
  restart count, uptime
- **Resource usage:** CPU/memory requests vs limits (progress bars)
- **Events table:** Kubernetes events with type (Normal/Warning), reason,
  message, timestamp, count
- **Warning banner:** When restarts > 0, show last restart reason prominently
  (e.g., red banner: "OOMKilled 6 times — consider increasing memory limit")
- **Auto-refresh:** Poll every 30s for updated status

### All Agent Pods — Not Just the Agent

Each wizard-deployed agent creates up to 3 pods. The Pod tab shows all of them:

| Pod | Deployment Name | Purpose |
|-----|----------------|---------|
| **Agent** | `{agent-name}` | LangGraph reasoning, tool execution |
| **Egress Proxy** | `{agent-name}-egress-proxy` | Squid domain allowlist |
| **LLM Budget Proxy** | `llm-budget-proxy` | Per-session token enforcement |

**Backend endpoint** returns status for all related pods:

```
GET /api/v1/sandbox/{namespace}/agents/{agent_name}/pod-status
```

Response includes an array of pod groups:

```json
{
  "pods": [
    {
      "component": "agent",
      "deployment": "rca-agent-emptydir",
      "replicas": 1,
      "ready_replicas": 1,
      "pod_name": "rca-agent-emptydir-675d59d779-c4r7p",
      "status": "Running",
      "restarts": 0,
      "resources": {"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"cpu": "500m", "memory": "1Gi"}},
      "events": [...]
    },
    {
      "component": "egress-proxy",
      "deployment": "rca-agent-emptydir-egress-proxy",
      "replicas": 1,
      "ready_replicas": 1,
      "pod_name": "rca-agent-emptydir-egress-proxy-9bd4c4498-6vjdr",
      "status": "Running",
      "restarts": 0,
      "resources": {"requests": {"cpu": "50m", "memory": "64Mi"}, "limits": {"cpu": "100m", "memory": "128Mi"}},
      "config": {"allowed_domains": ["github.com", "api.github.com", "githubusercontent.com", "pypi.org"]},
      "events": [...]
    },
    {
      "component": "llm-budget-proxy",
      "deployment": "llm-budget-proxy",
      "replicas": 1,
      "ready_replicas": 1,
      "pod_name": "llm-budget-proxy-7d5cd95575-42njh",
      "status": "Running",
      "restarts": 0,
      "resources": {"requests": {"cpu": "50m", "memory": "64Mi"}, "limits": {"cpu": "200m", "memory": "256Mi"}},
      "events": [...]
    }
  ]
}
```

**UI rendering** — each pod group gets a collapsible section:

```
[Agent: rca-agent-emptydir]        Running  0 restarts  1Gi/500m
[Egress Proxy]                     Running  0 restarts  128Mi/100m
  Allowed domains: github.com, api.github.com, ...
[LLM Budget Proxy]                 Running  0 restarts  256Mi/200m
```

Warning banners aggregate across all pods — if any pod is crashing, the
tab badge shows a warning indicator.

---

## Part 3: Resource Limits + Replicas in Wizard

### Problem

Resource limits (memory, CPU) and replica counts are hardcoded in deployment
YAMLs. Users can't configure them without kubectl access.

### Wizard Step: Resources

Add a new wizard step (or section in Budget step) for all 3 pod types:

```
Resources
---------
Agent Pod:
  Memory limit:  [1Gi    v]    CPU limit:  [500m   v]
  Replicas:      [1      v]

Egress Proxy:
  Memory limit:  [128Mi  v]    CPU limit:  [100m   v]
  Replicas:      [1      v]

LLM Budget Proxy (shared per namespace):
  Memory limit:  [256Mi  v]    CPU limit:  [200m   v]
  Replicas:      [1      v]
```

**Defaults:**

| Component | Memory | CPU | Replicas |
|-----------|--------|-----|----------|
| Agent | 1Gi | 500m | 1 |
| Egress Proxy | 128Mi | 100m | 1 |
| LLM Budget Proxy | 256Mi | 200m | 1 |

**WizardState additions:**

```typescript
// Step: Resources
agentMemoryLimit: string;    // "1Gi"
agentCpuLimit: string;       // "500m"
agentReplicas: number;       // 1
proxyMemoryLimit: string;    // "128Mi"
proxyCpuLimit: string;       // "100m"
proxyReplicas: number;       // 1
budgetProxyMemoryLimit: string;  // "256Mi"
budgetProxyCpuLimit: string;     // "200m"
budgetProxyReplicas: number;     // 1
```

**Backend** — `_build_deployment_manifest()` reads these from the request
and sets `resources.limits` and `spec.replicas` on each deployment.

---

## Session Assignment

| Feature | Session | Priority |
|---------|---------|----------|
| HITL proper (agent + backend) | Gamma P1 | High |
| HITL UI (approve/deny buttons) | Gamma P1 | High |
| Permission rule in HITL event | Gamma P1 | Medium |
| Pod events tab — all 3 pods (backend) | Delta P2 | Medium |
| Pod events tab — all 3 pods (UI) | Delta P2 | Medium |
| Resource limits in wizard | Delta P3 | Medium |
| Replicas in wizard | Delta P3 | Low |
