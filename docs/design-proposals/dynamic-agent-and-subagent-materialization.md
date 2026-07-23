---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Dynamic Agent and Subagent Materialization

## Summary

This proposal adds a Kubernetes-native mechanism for creating dynamic Rossoctl agents from an explicit request. The central API is a new `DynamicAgentRequest` custom resource watched by a new controller in the Rossoctl operator.

The proposal focuses on two MVP use cases:

1. **User-initiated dynamic agent creation**: a user, workflow, or higher-level system submits an explicit bill of materials describing an agent to create.
2. **Parent-agent-created subagent execution**: a running Rossoctl agent requests a task-scoped child agent, passes the task and required context, and receives the child result through a durable status/result channel.

The design reuses Rossoctl's existing primitives: dynamic agents are normal Rossoctl-managed agentic workloads. A dynamic agent may be materialized as a `Deployment`, `Job`, or `Sandbox`, and it should inherit the same behavior and limitations as the corresponding static workload type.

## Motivation and High-Level Direction

Static agents are useful when the set of tasks, tools, permissions, and runtime shape are known in advance. They become limiting when users or agents need short-lived, task-specific workers with narrower tools, smaller privileges, dedicated context, and clear audit boundaries.

Dynamic agent materialization enables Rossoctl to create a workload only when needed, with only the components and permissions required for the specific task. This creates a foundation for:

- task-specific agents with smaller privilege scope;
- parent agents delegating bounded work to child agents;
- better auditability of who created a workload and why;
- future task-scoped lifecycle controls;
- future session-aware interaction between parent and child agents;
- future integration with event-based agent communication.

This proposal is intentionally narrower than the larger long-term vision. It does not implement actual subagent orchestration, a component registry, general TTL-bounded lifecycle model, or session-based routing. Those can be added later on top of the same request/resource model.

## Goals

The MVP should:

- add a `DynamicAgentRequest` CRD containing explicit bill-of-materials input;
- implement a `DynamicAgentRequest` controller inside the existing Rossoctl operator;
- support both user-initiated dynamic agents and parent-agent-created subagents;
- provide a platform tool interface for parent agents to spawn, observe, and cancel subagents;
- support best-effort cancellation and cleanup consistent with existing Rossoctl behavior;
- preserve the behavior of existing Rossoctl workload creation paths as closely as possible.

## Non-Goals

The MVP does not:

- implement a new operator;
- change behavior of existing static agent creation flows;
- require full TTL lifecycle automation;
- implement a mature verified component registry;
- implement rich UI flows beyond basic CR visibility and future optional UI affordances.

## Current Rossoctl Primitives and Flows to Reuse

Rossoctl already supports most low-level primitives required for dynamic agent materialization, including:

- image-based deployment;
- source-based deployment through Shipwright `Build` and `BuildRun`;
- workload types `deployment`, `statefulset`, `job`, and `sandbox`;
- environment variables, including `Secret` and `ConfigMap` references;
- skill mounting from local skill `ConfigMap`s;
- external skill references fetched by init containers;
- Service creation for non-Job workloads;
- AgentRuntime creation for Deployment/StatefulSet workloads;
- AuthBridge, SPIRE, and mTLS configuration knobs;
- route creation where applicable;
- persistent storage for Sandbox workloads.

The dynamic controller should not disturb existing backend/UI-created static agents. It should create equivalent Kubernetes resources using the same naming, labels, annotations, and behavioral conventions wherever possible.

The first implementation will focus on *image-based materialization*. Source-based materialization through Shipwright is represented in the CRD shape and status model, but should be implemented as a follow-up because it requires build/finalize reconciliation beyond the immediate image-to-workload path. Until source support is implemented, the controller should reject `deploymentMethod: source` requests with a clear `UnsupportedDeploymentMethod` status reason rather than partially supporting them.

## Dynamic Agent Creation vs Subagent Execution

Dynamic Agent Materialization supports two closely related but different workflows.

In **standalone** mode, the request asks Rossoctl to create a dynamic agent workload from explicit inputs. The controller materializes the workload, records generated resource references in status, and leaves interaction to normal Rossoctl mechanisms such as A2A chat, ACP, routes, or Kubernetes visibility.

In **subagent** mode, the request asks Rossoctl to create a child agent **and run a task through it**. The task prompt, context, requested capabilities, and execution settings are part of the request. After materialization, the controller invokes the child through the selected workload/protocol path and writes the final result or artifact reference back to the same `DynamicAgentRequest` status. The parent receives progress and result through the platform tool wrapper, which reads the request status.

This distinction is important:

| Mode | What the controller creates | Does the controller invoke the agent? | How the caller gets the result | Typical caller |
|---|---|---|---|---|
| `standalone` | A normal Rossoctl-managed workload | No | Normal Rossoctl interaction paths | User, workflow, external planner |
| `subagent` | A normal Rossoctl-managed child workload | Yes | `status.result` or `status.artifactRef`, exposed through the tool wrapper | Parent agent |

The phrase "spawn subagent" therefore means more than "create another agent pod". It means creating a child workload, invoking it with a task, tracking failures and cancellation, and making the result available through a durable platform object.

## Proposed API: `DynamicAgentRequest`

`DynamicAgentRequest` is the durable source of truth for both dynamic agent creation and subagent execution. It contains an explicit bill-of-materials for instantiating a dynamic (sub-)agent.

The following is the conceptual shape of a `DynamicAgentRequest`:

```yaml
apiVersion: agent.rossoctl.dev/v1alpha1
kind: DynamicAgentRequest
metadata:
  # The request name is the stable handle used by users, controllers, and tools.
  # Generated workloads may derive their names from this value.
  name: review-pr-42
  namespace: team1

spec:
  # standalone: create a dynamic agent and expose it through normal Rossoctl mechanisms.
  # subagent: create a child agent, invoke it with spec.task, and store the result in status.
  mode: standalone | subagent

  requester:
    # Identifies who asked for the dynamic agent. For user-created CRs this may
    # come from admission; for tool-created subagent requests it must be stamped
    # by the trusted platform tool wrapper.
    type: user | workflow | agent
    subject: ...

  parent:
    # Present for subagent requests. This links the child request to the parent
    # agent/session for audit, cancellation, and result delivery. The trusted
    # tool wrapper should stamp these fields.
    agentRef:
      name: parent-agent
    sessionRef: optional-parent-session-id

  task:
    # Required for subagent mode. The controller passes this task to the
    # materialized child through the selected invocation path.
    prompt: |
      Review PR #42 for security issues and summarize findings.
    context:
      # Small structured context may be embedded directly. Larger context should
      # be passed by reference.
      inline: {}
      # Existing ConfigMaps may provide prompt/context files.
      configMapRefs: []
      # Package/workspace references are future-facing and should only be used
      # when the selected workload path supports them.
      packageRefs: []

  agent:
    # Reuses Rossoctl workload-type terminology.
    workloadType: deployment | job | sandbox

    # image is the MVP baseline. source is represented for compatibility with
    # Rossoctl's existing Shipwright flow but may initially return
    # UnsupportedDeploymentMethod until build/finalize reconciliation is added.
    deploymentMethod: image | source

    image:
      # Existing Rossoctl container-image field. Required when deploymentMethod=image.
      containerImage: ghcr.io/example/reviewer:latest
      imagePullSecret: optional-secret

    source:
      # Existing Rossoctl/Shipwright-style source inputs. Used only when
      # deploymentMethod=source is implemented for dynamic requests.
      gitUrl: optional-git-url
      gitRef: optional-branch-or-tag
      contextDir: optional-subdir
      dockerfilePath: Dockerfile

    # Declares how the controller or users should interact with the materialized
    # child. Valid combinations are constrained by workload type.
    protocol: a2a | acp | exec

    # Informational framework/harness metadata. The controller should not infer
    # hidden capabilities from this field.
    framework: LangGraph | ADK | ClaudeCode | OpenCode | other

    # Existing Rossoctl service port shape for Service-backed workloads. Ignored
    # or constrained for Job workloads.
    servicePorts:
      - name: http
        port: 8080
        targetPort: 8000
        protocol: TCP

    # Existing Rossoctl env var shape, including valueFrom Secret/ConfigMap refs.
    envVars: []

    # Existing Rossoctl skill names. Local skills are mounted from ConfigMaps;
    # external skills follow current Rossoctl external-skill behavior.
    skills: []

    # Optional model route/config reference. The MVP can translate this to
    # existing environment/config conventions rather than define a new model API.
    modelRef: optional-model-route-or-config-ref

  delegation:
    # Explicit child capability requests.
    requestedCapabilities: []
    requestedCredentials: []
    requestedEgress: []
    workspaceAccess: none | readOnly | readWrite

  materialization:
    # Existing Rossoctl materialization/security knobs.
    createRoute: false
    authBridgeEnabled: true
    authBridgeMode: proxy-sidecar | envoy-sidecar | lite | waypoint
    mtlsMode: disabled | permissive | strict
    spireEnabled: false
    outboundRoutes: []
    defaultOutboundPolicy: passthrough | exchange
    persistentStorage: {}

  execution:
    # wait: the parent-facing tool waits for completion or timeout.
    # background: return a handle immediately; parent can poll status later.
    # Primarily meaningful for subagent mode.
    mode: wait | background
    timeoutSeconds: 900
    resultSizeLimitBytes: 65536

  cleanup:
    # retain keeps generated resources after completion. deleteOnCompletion and
    # deleteOnFailure request best-effort cleanup by the controller.
    policy: retain | deleteOnCompletion | deleteOnFailure

  cancellation:
    # Optional observable cancellation request. Deleting the CR should also
    # trigger cleanup through finalizers/owner references.
    requested: false
    reason: ...
```

The CRD should use the existing Rossoctl API group and version convention, `agent.rossoctl.dev/v1alpha1`. Field names should mirror current Rossoctl agent creation terminology where possible, such as `workloadType`, `deploymentMethod`, `containerImage`, `servicePorts`, `envVars`, `skills`, `authBridgeMode`, `mtlsMode`, and `persistentStorage`.

A `DynamicAgentRequest` remains alive after the child workload is created because it records:

- who requested the dynamic agent;
- parent agent/session lineage, when applicable;
- what was requested;
- what was admitted;
- which workload resources were created;
- invocation status;
- result or artifact reference;
- cancellation and cleanup state.

## Status Model

The status model deliberately separates three concerns:

1. **Request phase**: where the overall request is in its lifecycle.
2. **Materialization state**: whether Kubernetes/Rossoctl resources were created.
3. **Execution state**: whether the child was invoked and produced a result.

Conceptual status:

```yaml
status:
  # Top-level lifecycle summary for quick kubectl/UI display.
  phase: Pending | Admitted | Materializing | Running | Completed | Failed | Cancelled

  admitted:
    # Records what the platform actually allowed. This may be narrower than
    # spec.delegation and is the source of truth for child authority.
    at: ...
    by: dynamic-agent-controller
    effectiveRequester: ...
    parentAgentRef: ...
    admittedCapabilities: []
    admittedCredentials: []
    admittedEgress: []
    admittedWorkspaceAccess: ...

  generatedAgent:
    # Stable identity and resource references for the materialized child.
    # Some refs are optional because not every workload type creates every
    # resource. For example, Jobs do not need Services, and Sandboxes inherit
    # the same AgentRuntime behavior as static Sandboxes.
    name: dyn-review-pr-42-a13f92
    namespace: team1
    workloadType: job
    serviceRef: ...
    workloadRef: ...
    agentRuntimeRef: ...
    routeRef: ...

  materialization:
    # Tracks creation of backing Rossoctl/Kubernetes resources. Source-based
    # requests may pass through BuildRunning before a workload exists.
    phase: Pending | BuildRunning | Materialized | Failed | PartiallyCreated
    buildRef: ...
    buildRunRef: ...
    generatedResources: []
    cleanup:
      # Best-effort cleanup report. This is not transactional rollback.
      attempted: false
      cleanedUpResources: []
      preservedResources: []
      errors: []

  execution:
    # Tracks task invocation. For standalone mode this may remain NotRequested.
    # For subagent mode it is the parent-visible task state.
    phase: NotRequested | Pending | Invoking | Running | Completed | Failed | Cancelled | TimedOut
    startedAt: ...
    completedAt: ...
    invocationProtocol: a2a | acp | exec
    error: ...

  result:
    # Small final output, suitable for CR status. The controller must enforce
    # resultSizeLimitBytes and move larger outputs to artifactRef.
    summary: ...
    content: ...
    truncated: false

  artifactRef:
    # Reference to larger or sensitive output. For MVP this should point to a
    # same-namespace ConfigMap, Secret, or PVC path. Object stores and OCI
    # artifacts are future extensions.
    kind: ConfigMap | Secret | PVC | ObjectStore | OCIArtifact
    name: ...
    key: ...

  observedMissingCapabilities:
    # Populated when execution fails because the admitted child scope was too
    # narrow for the task. This enables explicit retry without task inference.
    - github.contents.read

  conditions:
    # Kubernetes-style conditions for machine-readable status.
    - type: Admitted
      status: "True"
    - type: Materialized
      status: "True"
    - type: Completed
      status: "True"
```

Small results can be stored directly in `status.result`. Larger outputs should be stored in an artifact and referenced through `status.artifactRef`.

For the MVP, artifact storage should use Kubernetes-native resources in the same namespace as the request:

- a controller-created `ConfigMap` for non-sensitive text or JSON output that is too large for status;
- a controller-created `Secret` for sensitive output;
- an existing or request-owned PVC path only when the selected workload already uses workspace storage.

Richer artifact storage backends may be implemented as future extensions.

The controller should enforce a configurable result-size limit for `status.result` and set `result.truncated: true` when content is summarized or moved to an artifact.


## Controller Location and Responsibility

The new `DynamicAgentRequest` controller is running inside the Rossoctl operator. It watches `DynamicAgentRequest` resources and reconciles them through the following stages:

```text
DynamicAgentRequest created
        ↓
validate request
        ↓
authenticate/requester context resolved
        ↓
admit requested delegation scope
        ↓
materialize selected workload type
        ↓
wait for required readiness/build state
        ↓
invoke task if mode=subagent or execution requested
        ↓
store result / artifactRef
        ↓
cleanup according to policy or cancellation
```

The controller should support `Deployment`, `Job`, and `Sandbox` workload types.


### User-Initiated Dynamic Agent Flow

A user or workflow creates a `DynamicAgentRequest` with `spec.mode=standalone`.

Example flow:

```text
User/workflow creates DynamicAgentRequest
        ↓
Controller validates and admits request
        ↓
Controller creates the selected Rossoctl workload
        ↓
Controller stores generated resource references
        ↓
User interacts with the agent through normal Rossoctl mechanisms
```

For this use case, the request may not include an immediate task invocation. It can simply create a dynamic agent and expose references to the generated workload.

### Subagent Execution Flow

A parent agent creates a subagent through the platform-provided `spawn_subagent` tool. The tool creates a `DynamicAgentRequest` with `spec.mode=subagent`.

Example flow:

```text
Parent agent calls spawn_subagent
        ↓
Platform tool authenticates parent workload identity
        ↓
Tool creates DynamicAgentRequest with trusted parent/requester fields
        ↓
DynamicAgentRequest controller admits requested delegation scope
        ↓
Controller materializes child workload
        ↓
Controller invokes child with spec.task
        ↓
Controller stores result/artifactRef in status
        ↓
Parent watches/polls result through tool wrapper
```

The parent agent should not need raw Kubernetes credentials. It should use the platform tool interface (see below).

## Security Model and Delegation

The security model follows one central invariant: a dynamic agent must never receive more authority than the platform admits for the authenticated requester and the target namespace. For subagents, the child must also be bounded by the authenticated parent agent's delegable authority.

The parent or user may request capabilities, credentials, egress destinations, workspace access, model access, and skills. These requests are not grants. The `DynamicAgentRequest` controller computes the admitted scope as an intersection of the requested scope, the parent workload identity when applicable, the namespace policy, and the platform policy.

The platform should not infer required capabilities from arbitrary task text. Instead, the parent must request the capabilities it expects the child to need.

The parent agent must not be allowed to forge trusted identity or admission fields. Fields such as the requester, parent agent, parent session, effective subject, and admitted scope should be derived or stamped by the trusted platform path, not accepted as self-reported input from the agent.

Trusted identity and admitted-scope information should be represented in the request status, for example:

```yaml
status:
  admitted:
    effectiveRequester: ...
    parentAgentRef:
      namespace: team1
      name: parent-agent
    effectiveSubject:
      type: Agent | User | ServiceAccount
      name: ...
    admittedCapabilities: []
    admittedCredentials: []
    admittedEgress: []
    admittedWorkspaceAccess: readOnly
```

If the admitted scope is insufficient, the child may fail with a structured missing-capability error:

```yaml
status:
  phase: Failed
  reason: MissingCapability
  observedMissingCapabilities:
    - github.contents.read
  message: "Child attempted to use github.contents.read, but it was not admitted."
```

This creates a deterministic retry loop without relying on task inference. A parent or user can retry with a broader explicit request if policy allows it.

## Parent-Agent Tool Interface

The MVP must include a concrete parent-agent interface. The recommended approach is a built-in platform MCP server in the existing Rossoctl backend. This server exposes the `spawn_subagent`, `get_subagent_status`, and `cancel_subagent` tools over Streamable HTTP.

The backend MCP server does not directly materialize workloads. Its only persistent actions are to create, patch, and read `DynamicAgentRequest` CRs. The `DynamicAgentRequest` CR remains the durable API, and the controller in the existing Rossoctl operator remains responsible for reconciliation, materialization, task invocation, result capture, and cleanup.

### `spawn_subagent`

Purpose: create a task-scoped subagent and either wait for its result or return a handle.

Conceptual input:

```json
{
  "task": {
    "prompt": "Review PR #42 for security issues.",
    "context": {}
  },
  "agent": {
    "workloadType": "job",
    "deploymentMethod": "image",
    "image": "ghcr.io/example/security-reviewer:latest",
    "protocol": "a2a",
    "modelRef": "default-coding-model",
    "skills": ["security-review"]
  },
  "delegation": {
    "requestedCapabilities": ["github.pr.read", "github.contents.read"],
    "requestedCredentials": ["github-readonly-token"],
    "requestedEgress": ["api.github.com"],
    "workspaceAccess": "readOnly"
  },
  "execution": {
    "mode": "wait",
    "timeoutSeconds": 900,
    "resultSizeLimitBytes": 65536
  }
}
```

Conceptual response for wait mode:

```json
{
  "requestName": "review-pr-42-a13f92",
  "phase": "Completed",
  "result": {
    "summary": "2 medium-risk findings found.",
    "content": "..."
  },
  "artifactRef": null,
  "generatedAgentRef": {
    "namespace": "team1",
    "name": "dyn-review-pr-42-a13f92",
    "workloadType": "job"
  }
}
```

Conceptual response for background mode:

```json
{
  "requestName": "review-pr-42-a13f92",
  "phase": "Running",
  "message": "Subagent is running in background."
}
```

### `get_subagent_status`

Purpose: return current status/result for a previously created request.

Input:

```json
{
  "requestName": "review-pr-42-a13f92"
}
```

Output:

```json
{
  "phase": "Running",
  "materializationPhase": "Materialized",
  "executionPhase": "Running",
  "result": null,
  "artifactRef": null
}
```

### `cancel_subagent`

Purpose: request best-effort cancellation.

Input:

```json
{
  "requestName": "review-pr-42-a13f92",
  "reason": "Parent no longer needs this result."
}
```

The wrapper updates the request cancellation state or deletes the request, depending on implementation choice. The controller then performs best-effort cleanup of generated resources.

## Task Invocation and Result Capture

The controller is responsible for invoking the child task for subagent requests.

Invocation strategy depends on workload type and protocol:

| Workload | Invocation strategy |
|---|---|
| Deployment | wait for Service/workload readiness, invoke through A2A/ACP |
| Job | create Job with task input available through env/config/volume; watch completion and capture logs/artifact |
| Sandbox | invoke through existing Sandbox/OpenShell/exec path where applicable |

The controller stores:

- execution phase;
- error information;
- small result content in `status.result`;
- large output through `status.artifactRef`;
- generated workload references;
- cleanup state.

Future event/message-queue integration can provide streaming observations and event-based parent-child communication, but the MVP does not depend on it.

## Cancellation and Cleanup

Cancellation is best-effort and should align with current Rossoctl cleanup behavior.

Active cancellation should be represented by a spec field so the request can remain visible with a terminal `Cancelled` status:

```yaml
spec:
  cancellation:
    requested: true
    reason: ...
```

Deletion of the `DynamicAgentRequest` should also trigger cleanup through a finalizer. In other words, the MVP supports both patterns: spec-level cancellation for observable task termination, and deletion/finalizer cleanup for removing the request object and generated resources.

The controller should:

- stop waiting/invoking if possible;
- delete generated resources it owns when cleanup policy allows;
- avoid deleting pre-existing external resources;
- preserve externally supplied Secrets, ConfigMaps, PVCs, and package refs unless explicitly owned by the request;
- report cleanup errors in status.

For Jobs, deletion should use normal Kubernetes background propagation. For Sandboxes and other workloads, cleanup should follow existing Rossoctl deletion conventions.

## Labels and Annotations

Generated resources must be traceable to the request. The following labels are required on generated workloads and Services where Kubernetes label constraints allow them:

```yaml
rossoctl.io/dynamic-agent: "true"
rossoctl.io/dynamic-request: <request-name>
rossoctl.io/dynamic-mode: standalone | subagent
app.kubernetes.io/name: <generated-agent-name>
app.kubernetes.io/component: agent
app.kubernetes.io/managed-by: rossoctl-operator
```

For subagents, the following lineage labels should be added when the values fit Kubernetes label constraints:

```yaml
rossoctl.io/parent-agent: <parent-agent-name>
rossoctl.io/parent-namespace: <parent-agent-namespace>
```

Structured, large, sensitive, or potentially long values should be stored as annotations or status fields rather than labels. Recommended annotations:

```yaml
rossoctl.io/dynamic-request-uid: <request-uid>
rossoctl.io/requester-ref: ...
rossoctl.io/parent-session-ref: ...
rossoctl.io/admitted-capabilities-hash: ...
rossoctl.io/task-hash: ...
```

The controller should also set owner references from generated resources to the `DynamicAgentRequest` wherever Kubernetes ownership rules allow it. Owner references and finalizers are the primary cleanup mechanism; labels and annotations are for discovery, audit, and debugging.

## Naming

Generated agent names should be deterministic, readable, and unique within a namespace.

Recommended convention:

```text
dyn-<request-name>-<short-hash>
```

For example:

```text
dyn-review-pr-42-a13f92
```

The hash should be derived from request namespace, request name, request UID or generation, and admitted manifest.

If implementation constraints require the generated workload name to match the request name, the dynamic agent ID can be represented as a label or annotation instead.

## Reusable Materialization Layer

The implementation should not make workload materialization logic private to the `DynamicAgentRequest` controller. Dynamic agent requests and Teleport / restore workflows both need the same lower-level operation: given an admitted description of an agent-like workload, create or coordinate the corresponding Rossoctl resources using normal Rossoctl conventions.

The implementation should therefore introduce a small internal **reusable materialization package** inside the existing Rossoctl operator. The reusable materialization layer should own common mechanics such as:

- constructing `Deployment`, `Job`, or `Sandbox` resources from an admitted workload description;
- creating or referencing `Service` resources where appropriate;
- creating `AgentRuntime` for workload types that currently use `AgentRuntime` in Rossoctl;
- applying standard Rossoctl labels, annotations, owner references, and lineage metadata;
- wiring skills, environment variables, `Secret` and `ConfigMap` references, persistent storage, and context/package mounts using existing Rossoctl conventions;
- resolving skill-related dependencies;
- recording generated resource references;
- tracking which resources were created by a materialization operation;
- performing best-effort cleanup of resources owned by the materialization operation.

The `DynamicAgentRequest` controller remains responsible for dynamic-agent-specific behavior: request admission, parent/child linkage, delegated-scope admission, task invocation, result capture, cancellation state, and status updates.

Teleport / restore workflows remain responsible for Teleport-specific behavior: capturing local or session state, constructing restore packages, deciding what state should be mounted, handling reconnect or pull-back behavior, and any user-facing Teleport workflow.

## MVP Implementation Plan

### Step 1: Add CRD types

Add `DynamicAgentRequest` API types to `rossoctl-operator`, including spec/status and printer columns for phase, mode, workload type, and age.

### Step 2: Add controller

Add a new controller in the existing Rossoctl operator.

The first reconciliation loop should support:

- validation;
- status phase transitions;
- Deployment/Job/Sandbox resource creation;
- generated resource labels;
- basic readiness/status observation;
- result placeholder handling;
- cancellation and cleanup.

### Step 3: Implement materialization adapters

Implement workload-specific reconciliation paths:

- Deployment adapter;
- Job adapter;
- Sandbox adapter.

These should follow current Rossoctl backend conventions as closely as possible.

### Step 4: Implement subagent invocation

Add invocation support per protocol/workload:

- A2A invocation for Deployment-based agents;
- Job completion/log capture for Job-based subagents;
- Sandbox/exec invocation for Sandbox-based subagents.

### Step 5: Implement result storage

Store small results in `status.result`. Store larger outputs in an artifact and reference it via `status.artifactRef`.

### Step 6: Add platform tool wrapper

Add `spawn_subagent`, `get_subagent_status`, and `cancel_subagent` tools in the existing Rossoctl backend or existing Rossoctl platform service layer.

The tool wrapper should authenticate the caller through Rossoctl's existing workload/user authentication path, stamp trusted parent/requester metadata, create/update `DynamicAgentRequest` CRs, and read status. It should not give the parent agent raw Kubernetes credentials.

### Step 7: Add tests

Test:

- valid user-initiated dynamic request;
- valid subagent request;
- invalid request rejection;
- unsupported workload/protocol combination;
- Deployment materialization;
- Job materialization and result capture;
- Sandbox materialization and result capture;
- cancellation and cleanup;
- missing capability failure;
- label/annotation lineage.

## Future Work

Future extensions may add:

- richer capability-profile management;
- UI flows for creating and inspecting dynamic agents;
- event-based parent/child agent communication;
- session-based subagent interaction and background promotion;
- TTL and retention policies;
- richer artifact storage backends;
- stronger delegation policy models.
