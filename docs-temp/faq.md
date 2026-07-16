---
sidebar_label: FAQ
sidebar_position: 11
---

# FAQ

Short answers to the questions people ask most. Deeper answers live in the linked pages.

### Do I have to use a specific agent framework?

No. Rossoctl is framework-neutral — LangGraph, CrewAI, AG2, AutoGen, or a custom loop all work, as long as the agent speaks [A2A](concepts/agents.md). See [Bring your own agent](guides/bring-your-own-agent.md).

### How is this different from an agent framework?

Frameworks help you *build* an agent. Rossoctl is the platform that *runs* it — identity, governance, isolation, and observability on Kubernetes. It sits beneath your agent, not in place of it.

### Do agents need long-lived API keys?

No. Rossoctl issues cryptographic workload identity and short-lived, scoped tokens at runtime, so agents rarely need standing secrets. See [Security & Identity](security/overview.md).

### Can I run models locally?

Yes. Point agents at Ollama or any OpenAI-compatible endpoint — data never has to leave your network. See [Use local models](guides/use-local-models.md).

### Where does Rossoctl run?

Any conformant Kubernetes cluster: local [Kind](deployment/local-kind.md), [OpenShift](deployment/openshift.md), or via [Helm](deployment/helm.md).

### Is it safe to run autonomous, code-executing agents?

That's a core use case. Combine [sandboxing](guides/sandbox-agents.md) (kernel isolation + egress policy), [scoped policy](security/authorization-and-policy.md), and [audit](security/audit-and-governance.md) to contain and account for autonomous agents.

### What does it cost to run?

The platform is open source. Your real cost is infrastructure and model tokens — and Rossoctl attributes [token cost](observability/metrics-and-cost.md) per agent and team so you can see and control it.

### Why "Rossoctl" — I've seen "Kagenti"?

The project is being renamed from Kagenti to Rossoctl. You may see both names during the transition; they refer to the same platform.

:::note For contributors
Prune and reorder as real questions come in from users and the community. Keep answers to a few
sentences and link out for depth.
:::
