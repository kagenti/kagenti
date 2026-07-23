---
draft: true       # excluded from https://www.rossoctl.dev/
---

# rossoctl: Access Control Architecture

This directory contains the architectural blueprints, technical specifications, and implementation guidelines that govern rossoctl's zero-trust fine grain authorization. It discusses the challenges in authorizing multi-agent execution graphs where each agent may act as a confused deputy or be otherwise malicious and how rossoctl addresses such challenges.


## Architectural Philosophy: Fine-Grained Zero-Trust

The rossoctl platform operates under a strict **Zero-Trust Access Control** model. No internal communication channel, inter-agent message, or tool invocation is implicitly trusted. Every single step in an execution sequence requires explicit, context-aware authorization.

The rossoctl platform implements **Fine-Grained Authorization (FGA)**. In the current framework, this is achieved via specialized plugins that both enrich the context known during access decisions and have the authority to independently drop packets. Decisions take into account the user on whose behalf the agent operates, the task asked by the user, the agent identities, the tools involved, the actual content delivered, and the behaviors of the agents.

Note: While allowing plugins to directly execute drop decisions provides immediate FGA capabilities and maximal flexibility, it introduces severe configuration and debugging complexities as the multi-agent graph grows as discussed in **[Centralizing Zero-Trust Access Decisions in rossoctl](./zero-trust.md)**.

Security in rossoctl is enforced natively at the boundary of every runtime component via the Cortex (formerly AuthBridge) sidecar and gateway infrastructure. This distributed layout allows coping with the premises of zero trust where offenders are assumed to not only be outsiders but also insiders acting as part of the agent platform. Cortex offers control over four traffic directions, separating Requests from Responses to provide complete security coverage:

```                             
   ┌──────────┐  (1) INBOUND REQ    ┌─────────────────────────────┐  (2) OUTBOUND REQ   ┌───────────────────────┐ 
   │          │ ──────────────────► │ CORTEX  ┌────────┐ CORTEX   │ ──────────────────► │                       │
   │  CALLER  │                     │ INBOUND │ AGENT  │ OUTBOUND │                     │  TARGET AGENT / TOOL  │
   │          │ ◄────────────────── │         └────────┘          │ ◄────────────────── │                       │
   └──────────┘  (4) INBOUND RESP   └─────────────────────────────┘  (3) OUTBOUND RESP  └───────────────────────┘
```

1. Inbound Request: This path controls incoming traffic requests arriving at an agent. For example, Cortex verifies the caller’s identity, checks if the request serves a task sent by a user with the correct role, and ensures it does not include a dangerous prompt.

2. Outbound Request: This path controls outgoing traffic requests initiated by an agent. For example, Cortex checks if the agent while acting on behalf of the user is allowed to access a backend Database Agent or a given API or tool and ensures the content does not leak sensitive data.

3. Outbound Response: This path controls a response to an outgoing request sent by the agent. For example, Cortex checks that the response data does not include a malicious attempt to overtake the calling agent.

4. Inbound Response: This path controls an agent's response to the caller's request. For example, Cortex checks the response to ensure it does not include sensitive data that is unauthorized to be leaked to this user.


---

## Plugins

Details on each plugin participating in FGA. Documenting per plugin:
1. What information it adds to the Context
2. If it may drop packets, under what circumstances and what configuration parameters control such a decision

(TBD)
