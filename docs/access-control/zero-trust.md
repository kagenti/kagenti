---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Centralizing Zero-Trust Access Decisions in rossoctl

## 1. Executive Summary
The rossoctl platform operates on a zero-trust model where no internal communication is implicitly trusted, and explicit authorization is required at every execution hop. It enforces access control at every boundary via the Cortex (formerly AuthBridge) sidecar and gateway infrastructure. To mitigate the risk of an AI agent acting as a confused deputy, rossoctl introduces fine-grained access (FGA) per boundary. While this approach puts rossoctl at the forefront of access control, it introduces significant challenges.

As the platform grows, the overhead of managing and debugging request/response graphs grows exponentially. This document describes a strict architectural paradigm shift: dividing responsibilities between context-providing plugins and a centralized Access Control Engine governed by a cluster-scoped, multi-tiered rule hierarchy. This paradigm shift stands regardless of specific implementation details or technologies used. It is equally applicable to Cortex's current design, a potential [CPEX-based architecture](https://github.com/contextforge-org/cpex), or the deployment of Cortex within [Praxis](https://github.com/praxis/praxis). To establish a complete operational view, Section 5 outlines the scaling challenges inherent to multi-agent graphs, while the final section provides a full mapping to standard XACML framework terminology (PIPs, PDPs, and PEPs) for industry alignment.

## 2. Context & Problem Statement: The Complexity Explosion

In our current trajectory, access control and plugin configurations are dangerously decentralized. Because a single user task can trigger a highly complex graph of LLM and MCP tool requests, each governed by multiple plugins playing a role in access control, this decentralization creates an unmanageable explosion of independent enforcement points.

**The Operational Reality:**

* **Edge Volume (N):** Let **N** represent the number of execution graph edges per user task. Even a single agent handling an isolated task typically makes a few LLM calls and a few MCP tool calls, producing roughly **N=10** edges end-to-end. In multi-agent topologies, where tasks are delegated across a chain of specialized agents, each executing independent LLM and MCP loops, N scales with graph depth and breadth, readily reaching 50–100+.
* **Checkpoints (2N):** Each edge exposes 4 potential decision points (outbound request, inbound request, outbound response, inbound response). Assuming 2 are utilized on average, we hit **2N** execution checkpoints.
* **Hierarchical Evaluation (8N):** As discussed below, rossoctl is expected to support a multi-tiered access control where access rules from 4 distinct control tiers are evaluated, resulting in **8N** access decisions per user task.
* **The Plugin Multiplier (32N–40N):** Cortex's plugin architecture deployed in a cluster is expected to include multiple modules playing a role in access control. If each module is independently allowed to drop a request or response based on local logic and configuration, it follows that each Cortex sidecar is effectively running multiple, disjointed access control engines. Rather than evaluating a unified policy, each plugin acts as an autonomous gatekeeper. If we also allow per Cortex instance configurations for each plugin deployed, we allow each plugin to enforce its own implicit "access rules" based on localized configurations. Example plugins include: the instance-based access control (IBAC), input/output guardrails plugins, a data leakage prevention plugin, any behavioral anomaly detection plugin, and CPEX when it is configured with internal drop logic—all on top of the access control engine plugin. With 4-5 plugins autonomously blocking traffic per Cortex instance, it follows that we will be reaching 32N–40N distinct decision points per task.

To summarize, if we allow each plugin to be a decision point dropping the request/response, then in the single-agent case (N=10), we introduce 320–400 independent decision points that must work in concert to ensure a successful task. In the multi-agent graph case (N=100), we exceed 4,000 decision points. If we also allow individual plugins to be configurable, we are left with thousands of decentralized configuration points that the operator must meticulously align. We need to ask how we avoid creating an unmanageable matrix for debugging, auditing, and SRE incident response where a single misconfiguration anywhere in the graph can break an entire user task execution. This blast radius scales linearly with the platform's core value proposition: multi-agent orchestration. We must find ways to centralize this architecture.

## 3. The Multi-Tiered Access Control Model

To safely govern agent behavior without stifling flexibility, rossoctl must support an aggregated access control model that evaluates rules across four distinct control tiers:

| Tier | Persona | Purpose & Example |
| --- | --- | --- |
| **Cluster** | Platform Engineer | **Infrastructure Guardrails:** Fixed restrictions. *Example: Agents may never approach APIs outside of a fixed allow-list of MCPs and LLMs.* |
| **Namespace (NS)** | SRE | **Tenancy Isolation:** *Example: All agents in `NS-Finance` can only interact with other agents within `NS-Finance`.* |
| **Component** | SRE / Operator | **Role-Based Granularity (Agent/Gateway):** *Example: Restricting a specific agent when serving users with the 'Tech Support' role to only use a specific subset of tasks/tools.* |
| **Developer** | Agent Developer | **Behavioral Safety:** *Example: Adding infrastructure guardrails to the GitHub issue agent ensuring it only uses specific MCP tools, preventing it from acting as a confused deputy and causing damage.* |

**The AND Gate Enforcement Principle:**
Access is granted if and only if **all four tiers explicitly allow it**. The model functions as a strict logical AND gate. A denial at any single tier is sufficient to block the request, regardless of what the other three tiers permit. 

## 4. Architectural Ground Rules to Mitigate Complexity Explosion 

To eliminate decentralized configuration sprawl and to avoid creating an unmanageable matrix for debugging, auditing, and SRE incident response, the rossoctl platform should adopt the following principles:


### Principle 1: Uniform Plugin Topology and Drop Logic

Any deployed instance (cluster) of the rossoctl agent system maintains a globally fixed configuration for access control plugins.

* **Topological Consistency:** For each of the 4 traffic directions (inbound request, outbound request, inbound response, outbound response), the list and execution order of Cortex plugins is fixed and identical across all agents within that cluster.
* **Separation of Policy and State:** Plugins do not maintain independent, per-agent configuration states to evaluate access rules or execute drop decisions. Instead, agent-specific access logic is delegated to the centralized Access Control Engine (e.g., OPA) through the following pipeline:
  * **Context Enrichment:** Plugins analyze traffic using localized operational state and append their findings or indicators directly to the Cortex Context.
  * **Centralized Evaluation:** This context is passed into the Input Document evaluated by the Access Control Engine, ensuring all agent-specific drop decisions are expressed and executed through a unified set of access rules. Consequently, the Access Control Engine must be chained after all other plugins that rely on it to execute drop decisions.
* **Global Enforcement:** A plugin may directly execute drop decisions only if its underlying rules and configurations are strictly cluster-wide, ensuring identical drop conditions apply uniformly across all agents in the cluster. Note that an immediate drop decision executed by a plugin prevents subsequent context-aware evaluation, blocking cases where operators might otherwise require exceptions to the plugin's rule.

> **Architectural Note:** Plugins may still leverage cluster-wide configuration to determine whether to execute a localized drop decision or to enrich the context and rely on the downstream Access Control Engine for the final decision as described above.



### Principle 2: Unified Decision Execution and Context Passing

Unless a plugin is enforcing strict cryptographic identity validation or token presence (Authentication), all agent-specific access control decisions (Authorization) are executed exclusively within a centralized Access Control Engine, never as side-effects of independent plugin configurations.

* **The Hard Line: Authentication (AuthN) vs. Authorization (AuthZ):** 
    * **AuthN (Identity Validation):** Plugins responsible for verifying *who* an entity is (e.g., Mutual TLS validation, cryptographic signature verification, checking token expiration) are encouraged to utilize **fail-fast drop logic**. If an identity or token is missing or cannot be cryptographically proven valid, the plugin should drop the request immediately at the edge to protect the platform from Denial of Service (DoS).
    * **AuthZ (Context & Permissions):** Plugins evaluating claims, token audiences (`aud`), user delegation contexts, data payload contents, or behavioral metrics must defer drop decisions and pass context to the central Access Control Engine.

* **The Operator-Controlled Route for Authorization & Behavioral Plugins:** Even when security plugins identify high-risk anomalies or payload mismatches, applying localized, binary drop rules can disrupt complex agent orchestration. Whether validating internal token claims (like target `aud` and user impersonation) or running content analysis to implement input guardrails, plugins must not execute an immediate localized drop. Instead, they must append their findings as structured metadata flags to the request context.

* **Concrete Examples of Deferred Decision Context:**
    * **Token Claims:** A token verification plugin encounters a valid signature but a mismatch on delegation. It appends: `token_crypto_valid: true, on_behalf_of: "exec_user", audience_match: false`.
    * **Input/Output Guardrails (or Data Leak Prevention):** A PII inspection plugin detects sensitive data in an outbound response. It appends: `pii_detected: true, data_type: "SSN"`.
    
    The central Access Control Engine then ingests these flags simultaneously, evaluating them against the multi-tiered rule hierarchy to determine the final, atomic allow/deny decision.

> **Why this matters:** Deferring drop decisions to a central engine simplifies platform operations in two ways:
> * **Centralized Troubleshooting:** Operators can manage complex rule exceptions (like multi-agent token delegation or cross-namespace talk) in one policy codebase, rather than managing hidden, scattered rules inside individual sidecar configurations.
> * **Clear Auditing:** It ensures every single allow/deny decision is explicitly logged and evaluated in one place, making incident response fast and predictable.


### Principle 3: Structured Context Contracts

The input document provided to the central Access Control Engine is governed by a well-documented, versioned schema that serves as the explicit interface between the context-providing plugins and the policy engine.

* **Explicit Ownership:** Every field or flag within the schema is owned by exactly one plugin. The schema strictly defines which plugin is responsible for populating each field, the precise conditions under which it is present, and its explicit data type. 
* **Lifecycle Management:** This input contract is maintained as a versioned artifact alongside the plugin and policy codebases, establishing joint ownership between policy authors and plugin developers.

**TBD — Areas requiring further discussion:** 
1. **Plugin Failures:** How do we handle plugin failures? Should a plugin failure result in immediately dropping the request/response? If not, we may have missing context for later evaluation—how do we safely handle that state?
2. **Contract Rigor:** What else is needed to deterministically define the contract between a plugin and the Access Control Engine?



## 5. Architectural Blind Spot: The Residual 8N Evaluation Scale Problem

While the proposed paradigm shift successfully eliminates the decentralized plugin configuration multiplier (reducing potential checkpoints from $32N–40N$ to a structured $8N$), we must still address the massive remaining volume of decision points. In a complex multi-agent topology where $N=100$, the platform is still forced to execute, evaluate, and audit up to 800 distinct access decisions per user task. 

Further research is required to tackle the resulting operational and technical complexities, specifically:

* **Policy Synchronization Overhead:** What are the implications and architectural trade-offs of synchronizing real-time policy updates across thousands of active decision points across the cluster?
* **Observability and Debugging:** How can operators achieve clear visibility, per-task traceability, and rapid root-cause analysis when an execution graph generates hundreds of discrete access evaluation logs?
* **Graph-Aware Authorization:** How can the platform shift toward making educated, context-aware decisions based on the state of the overall task graph, rather than relying strictly on isolated, localized Cortex decisions?


## Summary: Architectural Component Mapping

To align the rossoctl platform with standard access control reference models, the system components map to Policy Information, Decision, and Enforcement Points as defined in XACML:

* **Policy Information Points (PIPs) — The Plugins:** Many Cortex plugins serve primarily as PIPs. Their role is to inspect traffic, parse payloads, evaluate localized state, and deliver their security findings as structured data flags directly into the Cortex Context.
* **Policy Decision Point (PDP) — The Central Access Control Engine:** For each of the four traffic combinations (inbound/outbound request/response), there is exactly one PDP evaluation phase. The embedded access control engine ingests the compiled Cortex Context contract and renders a single, atomic allow/deny decision against the unified rule hierarchy.
* **Policy Enforcement Point (PEP) — The Gateway Boundary:** For each traffic combination, there is exactly one PEP phase. The sidecar layer receives the PDP's decision and executes the final action—allowing the traffic to pass or executing an immediate drop.

### The Hybrid Enforcement Design

While the architecture consolidates access rules into a centralized PDP to keep cluster operations predictable and manageable, it accommodates localized enforcement when required:

* **Localized Drops:** Plugin developers may configure a plugin to act as an immediate, local PEP and drop packets directly when technical or protocol constraints demand it.
* **Centralized Rule Sovereignty:** Even when localized drops are utilized, the underlying access rules, configurations, and drop conditions must remain strictly cluster-wide. This ensures that operators retain a sensible, unified view of the system's security posture without tracking decentralized sidecar configurations.
