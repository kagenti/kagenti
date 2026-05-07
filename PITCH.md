# Kagenti — Pitch

## Table of Contents

- [You have AI agents and you want to run them in enterprise?](#you-have-ai-agents-and-you-want-to-run-them-in-enterprise)
- [Why Kagenti?](#why-kagenti)
- [The mental model](#the-mental-model)
- [Quick tour](#quick-tour)
- [See it working](#see-it-working)
  - [1. Every agent has a cryptographic identity](#1-every-agent-has-a-cryptographic-identity)
  - [2. The agent can't steal the HR docs](#2-the-agent-cant-steal-the-hr-docs)
  - [3. Unauthorized namespaces get a wall, not a door](#3-unauthorized-namespaces-get-a-wall-not-a-door)
  - [4. Framework doesn't matter — A2A is the interface](#4-framework-doesnt-matter--a2a-is-the-interface)
  - [5. Every LLM call is traced](#5-every-llm-call-is-traced)
  - [6. Fifteen providers, one proxy](#6-fifteen-providers-one-proxy)
- [What you build on top](#what-you-build-on-top)
- [Further reading](#further-reading)

## You have AI agents and you want to run them in enterprise?

You have many AI agents and they work great, they use a LangGraph workflow, a CrewAI team, an AG2 ensemble — pick your framework. 

Now you want it to keep working when real users show up.

And you have a list.

**It can't scale to an organization.**
- You deployed on your namespace. Your colleague wants one too. Now you need RBAC, tenant isolation, per-team credentials, shared observability. You thought you were building agents. You're now building a platform.
- Six months from now, someone ships a better model. Your agents are bolted to one provider. Migrating is a sprint.
- Nobody can tell you which agent called which model, how many tokens it burned, or whether it hallucinated its way through a customer interaction. You have logs. You don't have observability.

**It doesn't interoperate.**
- Agent A is LangGraph. Agent B is CrewAI. They can't talk to each other without custom glue code, subprocess wrappers, and file-based session hacks.
- Your tool integrations are copy-pasted across agents. Each one has its own HTTP client, its own auth dance, its own retry logic. One breaks and you don't know until a user reports garbage output.
- You want to add a new agent from a different team. Now you need to understand their framework, their serialization format, their state model. Integration is a weekend per agent.

**It's not secure.**
- The agent has a user's access token in an env var. Developers paste tokens; agents read them. One prompt injection and the agent is making requests *as that user* — with all their groups, all their permissions. Your HR docs, your admin APIs, your secrets. The agent didn't hack anything. It just used the credential it was given.
- The agent is persistent and creative. In red-team testing, Claude made 41 tool calls in 10 minutes — resolving ClusterIP addresses, probing alternative routes, trying kubectl for lateral paths. It didn't stop because the first attempt failed. System prompts say "be thorough." The agent obliged.
- Static credentials sit in Secrets for months. Nobody rotates them. Nobody audits which agent called which model. Your "AI platform" is a compliance incident waiting to happen.
- You deployed five agents. They all talk to each other over plaintext HTTP inside the cluster. Any compromised pod can impersonate any other agent. There is no identity. An agent that discovers a service's ClusterIP can bypass hostname-based allowlists entirely — the logs say "passthrough" and the data walks out.

None of this is the framework's fault. Frameworks are great at being frameworks. They're bad at being production platforms because that was never their job.

Kagenti signed up for that job.

## Why Kagenti?

Kagenti is the Kubernetes control plane for AI agents. You bring the agent — any framework, any model. Kagenti gives it zero-trust identity, mutual TLS, protocol-native interoperability, LLM observability, and multi-tenant governance.

**Zero-trust** is doing real work in that sentence. Each agent gets a cryptographic identity via SPIRE — a SPIFFE ID, an X.509 certificate that rotates automatically, and an OAuth2 token exchanged from it. Not a shared API key. Not a service account token you created once and forgot. A real workload identity, per agent, rotated continuously, because that's what SPIFFE gives you when you use it honestly.

The agent doesn't know any of that is happening. It runs the same way it ran on your laptop. It just runs securely.

Here's the mapping to the three problems:

| The problem | Kagenti's answer |
|---|---|
| Agents inherit user credentials | AuthBridge intercepts every outbound request and performs OAuth2 token exchange (RFC 8693). The exchanged token carries *two* identities: `sub` = the human delegator, `azp` = the agent's SPIFFE identity. Access is the *intersection* of user groups and agent capabilities — not the union. User has HR access but agent is registered for engineering only? Agent gets engineering. Structurally. |
| Agents bypass hostname allowlists | Inverted network policy. Instead of blocking known-bad destinations, Kagenti allowlists known-safe services and forces token exchange for *all* other plaintext HTTP. Resolve the ClusterIP, hit it raw — doesn't matter. The traffic still hits AuthBridge. No "passthrough" default. |
| No identity, static creds | Every agent pod gets a SPIFFE identity via SPIRE. Certificates rotate automatically. OAuth2 tokens are exchanged from X.509 SVIDs — no static secrets in env vars. If a pod is compromised, the credential expires before you finish reading this sentence. |
| Agents can't talk to each other | A2A (Agent-to-Agent) protocol. Every agent publishes an Agent Card at `/.well-known/agent-card.json`. Communication is JSON-RPC 2.0 over mTLS. Framework doesn't matter — if it speaks HTTP, it speaks A2A. Tools are MCP servers routed through a gateway. |
| Can't scale to an org | Namespace-per-team isolation. Istio Ambient mesh enforces mTLS at L4 without sidecar overhead competing with inference. AuthorizationPolicies control which namespaces can talk. Keycloak handles human auth. Phoenix + OpenTelemetry trace every LLM call. One Ansible playbook deploys the whole stack. |

**Kagenti has no opinions about your agent.** No prompt templates, no memory format, no proprietary SDK. Bring a container that exposes A2A-compatible HTTP and Kagenti will secure it, connect it, observe it, and govern it. Framework-agnostic by construction.

## The mental model

Kagenti orchestrates agents using Kubernetes-native primitives and two open protocols.

**A2A (Agent-to-Agent)** — the Linux Foundation standard for agent interoperability. Each agent publishes an Agent Card describing its capabilities, authentication requirements, and endpoints. Agents communicate via JSON-RPC 2.0 over HTTPS. Kagenti enforces this with an AgentCard CRD that indexes deployed agents for discovery.

**MCP (Model Context Protocol)** — the standard for tool integration. Tools run as MCP servers. Kagenti's MCP Gateway routes tool calls from any agent to any tool with protocol translation and auth injection. One tool, many agents. No copy-paste.

**Deployment** — an agent is a standard Kubernetes Deployment. No CRDs for the workload itself (the old Component CRD is deprecated). You bring a container image. Kagenti's operators inject the SPIFFE sidecar, configure the mesh, register the Agent Card, and wire observability. `kubectl apply` is the deployment API.

**Namespace isolation** — teams get namespaces. `team1` and `team2` can't see each other's agents unless an AuthorizationPolicy explicitly allows it. Unauthorized connections are reset at L4 — TCP RST before HTTP even starts. Not a 403. A wall.

**Observability** — Phoenix traces every LLM interaction: prompts, completions, tool calls, latency. OpenTelemetry exports to your collector. Kiali visualizes the mesh. You can answer "which agent called which model with what prompt and what did it cost" for every request.

## Quick tour

Prerequisites: Docker, a Kubernetes cluster (Kind works), Ansible.

**Install the platform:**

```sh
# Kind (local development)
bash .github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy

# OpenShift
./deployments/ansible/run-install.sh --env ocp
```

That deploys the whole stack: Keycloak, SPIRE, Istio Ambient, MCP Gateway, Phoenix, the backend API, and the UI.

**Install the ADK (developer toolkit):**

```sh
curl -sSL https://kagenti.github.io/.github/install.sh | bash
```

**Start locally:**

```sh
kagenti platform start
```

**List available agents:**

```sh
kagenti agent list
```

**Run an agent:**

```sh
kagenti agent run
```

**Open the UI:** Navigate to `http://adk.localtest.me:8080`. Import agents, run tests, monitor deployments, manage the platform.

## See it working

Some demos of what's actually happening in your cluster.

### 1. Every agent has a cryptographic identity

```sh
kubectl exec -n team1 <agent-pod> -- \
  cat /run/spire/svids/svid.pem | openssl x509 -noout -subject -dates
```

A valid X.509 certificate. SPIFFE ID: `spiffe://localtest.me/ns/team1/sa/<agent-sa>`. Rotated automatically. No human touched it.

### 2. The agent can't steal the HR docs

Give Claude a user token for someone with HR access. Register the agent's capabilities as `["engineering"]` only. Let it try:

```sh
# Claude's 41 tool calls over 10 minutes:
# - Direct request with Alex's token → "token exchange failed"
# - Resolve ClusterIP, hit raw IP → intercepted, "token exchange failed"  
# - kubectl get svc, kubectl get endpoints → RBAC denied
# - curl alternative ports → no route
# All 15 conversational turns. Zero HR documents retrieved.
```

The exchanged token tells the whole story:

```json
{
  "sub": "alex",
  "azp": "spiffe://localtest.me/ns/team1/sa/claude-agent",
  "groups": ["engineering", "hr"],
  "effective_scope": ["engineering"]
}
```

`effective_scope` = `user_groups ∩ agent_capabilities`. Alex has HR access. Claude doesn't. The credential is valid. The access is not. That's not a policy you configure per-request — it's structural, enforced at the token exchange layer before the request reaches the target service.

### 3. Unauthorized namespaces get a wall, not a door

From `team2`, try to reach an agent in `team1`:

```sh
kubectl exec -n team2 <pod> -- \
  curl -s --max-time 3 http://<team1-agent>.team1.svc:8080/.well-known/agent-card.json \
  || echo "CONNECTION RESET"
```

`CONNECTION RESET`. The Istio ztunnel (Rust, per-node) enforces the AuthorizationPolicy at L4. TCP connection is killed before HTTP. Not a framework-level check — kernel-level enforcement via the mesh. One agent's compromise can't reach another namespace.

### 4. Framework doesn't matter — A2A is the interface

Deploy a LangGraph agent and a CrewAI agent. They discover each other via Agent Cards and communicate over JSON-RPC 2.0 with mTLS. No glue code, no subprocess wrappers, no framework-specific serialization:

```sh
# LangGraph agent discovers CrewAI agent
curl -s https://<crewai-agent>.team1.svc/.well-known/agent-card.json | jq .capabilities
```

BeeAI framework achieved 87% code reduction (325 lines to 40 lines) by adopting A2A natively versus CLI wrappers. Eliminates subprocess injection risks, file-based session storage vulnerabilities, and manual protocol construction errors.

### 5. Every LLM call is traced

Open Phoenix at the configured endpoint. Every agent interaction is traced end-to-end: the prompt, the completion, the tool calls, the latency, the token count. Not just logs — structured traces with OpenTelemetry spans. You can answer "what did agent X say to model Y at 3:47am and why" without grepping.

### 6. Fifteen providers, one proxy

```sh
# Agent code doesn't know or care which provider is behind the proxy
curl -s http://litellm.kagenti-system.svc/v1/models | jq '.data[].id'
```

OpenAI, Anthropic, watsonx.ai, Amazon Bedrock, Ollama — all behind one proxy endpoint. Swap providers without touching agent code. Per-agent cost tracking comes from the proxy layer, not the agent.

## What you build on top

Four things that become possible once the floor is there.

**1. Multi-agent workflows across teams.** Team A's research agent feeds findings to Team B's summarization agent via A2A. Each team owns their namespace, their credentials, their policies. The mesh handles auth. The protocol handles interop. Nobody wrote integration code.

**2. Governed AI for regulated industries.** Every LLM interaction is traced. Every agent has a cryptographic identity. Every cross-namespace call is policy-enforced. Capability intersection means an agent deployed for engineering can't touch HR data — even if the human who launched it can. When compliance asks "which agent accessed customer data and what did it do with it" — you have the answer. Structurally. Not "we trust the agent to log."

**3. The agent marketplace.** Your platform team publishes agent templates. Product teams deploy instances. Each instance gets its own identity, its own credentials, its own observability. The platform team sees everything. Product teams see their namespace. RBAC is Kubernetes RBAC — you already know it.

**4. Framework migration without downtime.** Your LangGraph agent is fine but you want to try CrewAI. Deploy the new one alongside the old one. Both expose A2A. Route traffic gradually. When the new one works, delete the old one. The protocol is the contract, not the framework. Migration is a deployment, not a rewrite.

---

## Further reading

- [When Claude Tried to Steal the HR Docs — A Kagenti Red Team Story](https://medium.com/kagenti-the-agentic-platform/when-claude-tried-to-steal-the-hr-docs-a-kagenti-red-team-story-ed12a00e00a5)
- [Zero Trust AI Agents on Kubernetes: What I Learned Deploying Multi-Agent Systems on Kagenti](https://next.redhat.com/2026/03/05/zero-trust-ai-agents-on-kubernetes-what-i-learned-deploying-multi-agent-systems-on-kagenti/)
- [How Kagenti ADK Simplifies Production AI Agent Management](https://developers.redhat.com/articles/2026/05/04/how-kagenti-adk-simplifies-production-ai-agent-management)
