# Rosso — A Platform for Governed, Zero-Trust Agent Autonomy

## The shift already underway

Software is learning to act on its own. AI agents no longer just answer questions — they plan, call tools, spend money, move data, and delegate to other agents to finish work that unfolds over minutes, hours, or days. The unit of computation is no longer a request that arrives and returns. It is an autonomous actor that reasons, remembers, and reaches out into the world on someone's behalf.

Our infrastructure was not built for this. The cloud-native stack assumes deterministic services with fixed identities, stable filesystems, short-lived requests, and permissions granted ahead of time. Agents violate every one of those assumptions. They are non-deterministic, long-running, stateful, and — most consequentially — they act with authority they were lent rather than authority they own. When an agent decides at runtime which tool to call and which data to touch, the guarantees that made cloud-native software safe to operate simply don't hold.

**Rosso exists to close that gap.** We are defining and building the platform primitives that autonomous agents need to run in production the way real organizations require: provable identity, delegated authority, enforceable policy, durable memory, and governed reach — all by default, and all without asking agent developers to become security engineers.

## The problem, stated plainly

An agent is the hardest thing to secure that we have ever deployed, because it combines three properties we have historically kept apart:

- It is **autonomous** — it chooses its own actions at runtime, so you cannot enumerate its behavior in advance.
- It is **privileged** — to be useful it holds credentials, reaches external APIs, and acts for a human user.
- It is **influenced by untrusted input** — everything it reads (a web page, a document, another agent's message) can steer what it does next.

Put those together and the classic controls fail. Static roles are too blunt for an actor whose correct permissions depend on the user, the task, and the moment. Long-lived secrets stored near the agent are one prompt injection away from exfiltration. Signed manifests prove who *published* an agent but not what it is *actually doing* right now. A human who delegated a task has no way to stay in the loop for the one action that turns out to matter. And a stateless agent, restarted, forgets everything it was doing.

The industry is converging on shared protocols for how agents talk — A2A for agent-to-agent, MCP for agents-to-tools. Rosso's bet is that the protocols are necessary but not sufficient. What's missing is the **trust, memory, and governance fabric underneath them**: the primitives that decide who an agent is, what it may do, on whose behalf, with what it remembers, and how far it can reach.

We organize that fabric into three pillars — an **Identity Fabric**, a **Governance Plane**, and a **Runtime Substrate** — and describe each capability as an arc: what we are building on the platform today, and the research frontier we are steering it toward.

---

## Pillar I — The Identity Fabric

*Who an agent is, what it is made of, and whose authority it carries.*

### Attested Identity — who an agent provably is

**Today:** Every agent is given a cryptographic identity rooted in the workload itself, not in a secret handed to it. Rosso goes beyond signing an agent's published card: a runtime attester *observes the running workload* and cryptographically vouches for what it actually is — its image, its platform claims, its integrity — producing a runtime-attested identity a consumer can trust for access decisions.

**Horizon:** Identity becomes continuous and compositional — issued, attested, and continuously true rather than asserted once and assumed forever, and eventually extending down to individual skills and tool calls so that trust is verifiable at every level of the stack.

### Skill & Supply-Chain Integrity — what the agent is made of

**Today:** Agents are increasingly assembled from skills, prompts, and capabilities pulled from external registries — a supply chain with no integrity story. Rosso is building verification that ties an agent's *authority* to the integrity of its *components*.

**Horizon:** We bind a signature-verified skill digest into the agent's attested identity, so that a tampered or unverifiable skill changes the identity and its access falls away automatically — fail-closed by construction. Supply-chain compromise stops being a detection problem and becomes an impossibility of the trust model.

### Delegation & Consent — acting for a user, with bounded authority

**Today:** When an agent acts on your behalf, it should carry exactly the authority you granted, for exactly as long as it needs it. Rosso provides just-in-time, user-scoped delegation: an under-privileged agent obtains ephemeral, narrowly-scoped credentials at the moment it needs them, through a consent flow in which neither the agent nor the platform ever holds the user's credentials.

**Horizon:** Delegation becomes contextual and revocable end-to-end — authority that is minted for a single intent, provably scoped to it, and dissolves the instant the task completes.

---

## Pillar II — The Governance Plane

*What an agent may do, decided from full context, with a human where it counts.*

### Policy & Decision — one auditable verdict, from complete information

**Today:** Correct authorization for an agent depends on the caller, the callee, the user, and the task — far too rich for group-level roles. Rosso is building a fine-grained, context-aware policy layer where a single, auditable policy decision point renders every allow/deny verdict from complete information, rather than fragmenting authority across components that each decide with a partial view.

**Horizon:** Policy expressed in *human language*. The platform infers an agent's intended behavior and derives — then continuously audits — the fine-grained rules that match it, keeping intent and enforcement in sync as the agent fleet grows beyond what any security team could hand-author.

### Human-in-the-Loop — from micro-management to delegated trust

We are redefining the human–agent relationship, shifting from active micro-management today to a future of autonomous decisions through delegated trust. In the near term, we are instrumenting the platform to continuously monitor long-running, event-driven, and asynchronous agents, enabling seamless human-in-the-loop interaction — such as mobile notifications — to safely verify high-risk actions and harvest direct feedback. For the long term, we are researching the **Agentic Avatar (Surrogate Agent)**, a personalized cognitive representation in code that replaces repetitive manual micro-approvals. By dynamically learning the user's habits, risk tolerances, and implicit intentions, this backend proxy safely auto-approves agent actions on the user's behalf — evolving the platform from a reactive notification system into a trusted, proactive digital representative.

### Cost & Budget Governance — autonomy with a spending limit

**Today:** An autonomous agent that calls models in a loop can consume unbounded cost. Rosso enforces token and budget quotas at the platform layer — per team, per user, per session — with pre-request hard limits and an infrastructure-level circuit breaker that halts a runaway session before the bill arrives, not after.

**Horizon:** Budget becomes a first-class dimension of every authorization decision, enabling fair multi-tenant economics, FinOps chargeback, and cost as a governed resource rather than a surprise.

### Data Security & Governance — context on every decision

**Today:** Data flows through an agent platform — in prompts, out through tool calls, across sessions and users — with no centralized governance. Rosso is building data-aware controls: classifying and tracing data lineage across agent trajectories, detecting breach and corruption risk, and feeding that context into policy decisions so an unsafe action can be blocked *before* it happens.

**Horizon:** The platform understands not just *whether* an action is allowed but *what data* it would move and where that data came from — closing the confused-deputy and exfiltration gaps that static controls cannot see.

### Quality & Evaluation — trusting the governors themselves

**Today:** As the platform's own governance components become autonomous — an agent that authors access policy, for instance — they need the same rigor we demand of the agents they govern. Rosso is building a quality framework of guardrails, adversarial testing, and evaluation (deterministic assertions alongside LLM- and agent-as-judge techniques) for its control-plane agents.

**Horizon:** Governed autonomy that is itself continuously validated — a platform whose safety properties are measured and regression-tested, not merely asserted.

---

## Pillar III — The Runtime Substrate

*How an agent lives, remembers, recovers, and reaches the world.*

### State, Session & Resiliency — durable, recoverable, portable

**Today:** Agents are stateful in ways cloud-native primitives never anticipated: they assume a stable filesystem, a single writer, an uninterrupted process. Production offers none of those. Rosso externalizes session state into a durable, append-only log so a session survives eviction, recovers after a crash with zero lost work, and can *move* between runtime instances.

**Horizon:** A serverless model for agents — scale-to-zero when idle, fast cold-start regardless of how long the conversation has run, and session mobility and self-healing recovery as native platform capabilities rather than bespoke integrations each team rebuilds.

### Long-Term Memory — the cognitive foundation

We are building the cognitive foundation for next-generation AI by transforming how autonomous agents remember, marrying immediate software systems with long-term neural design. In the near term, we are establishing **Long-Term Memory (LTM) as a platform-managed middleware layer** to continuously hydrate stateless agents with vital operational context at runtime. But stateful hydration is just the first step: our long-term research introduces **brain-inspired representation plasticity** to this layer, treating stored document vectors as mutable coordinates that warp, drift, and split under the gravity of live query streams. By uniting robust context plumbing with this adaptive memory manifold, we are creating a self-healing retrieval system that organically tracks shifting enterprise language without ever needing to touch the underlying, frozen LLM weights.

### Eventing & Governed Egress — communication and reach the agent can't abuse

**Today:** Agents talk to each other and reach out to the world, and both paths must be governed without rewriting the agent. Rosso treats inter-agent and tool traffic as signed, identity-carrying events, so no unauthorized party can impersonate an agent, tamper with a message, or publish where it shouldn't — enabling the long-running, asynchronous, approval-gated workflows synchronous calls can't support. On egress, a zero-trust credential plane keeps secrets only in an identity-aware broker that injects them at the network layer, keyed to the workload's identity.

**Horizon:** No component influenced by model output — not the agent, not its sandbox, not its logs — ever holds a raw credential. The agent gets to *use* a credential it can never *read*, for any destination, through one unified mechanism.

### Multi-Tenant Sandbox Isolation — safe execution by construction

**Today:** Autonomous code execution demands strong isolation. Rosso runs agents in isolated, per-tenant sandboxes with defense-in-depth — network, filesystem, and identity boundaries — and a one-namespace-per-user model, so a compromised or misbehaving agent is contained by construction rather than by trust.

**Horizon:** Sandboxes that are disposable, instantly provisioned, and portable — a user's full working environment teleported into a governed remote runtime and torn down when done, with isolation strong enough that the platform can safely run untrusted agents from anywhere.

### Extensible Plugin Pipeline — a governed extensibility model

**Today:** The controls above — identity, policy, guardrails, protocol handling — are not a monolith. Rosso exposes them as a versioned plugin pipeline with a stable contract, so guardrail, policy, and context-engineering capabilities from across the ecosystem compose into the agent's request path without each team building its own interception layer.

**Horizon:** An open extensibility standard for agent governance — a single, runtime-agnostic contract that lets the community contribute policy engines, guardrails, and context tooling that any Rosso deployment can adopt.

---

## What the primitives compose into: governed autonomy

Taken one at a time, these are features. Taken together, they are something new: a platform on which an agent can be genuinely autonomous *and* genuinely governable at the same time.

Attested identity means you know what you're trusting, down to the skills it's made of. Delegation and consent mean the agent acts with borrowed, bounded, revocable authority — and a human, or eventually that human's trusted surrogate, in the loop where it counts. Policy decides every action from full context, within a budget, with data lineage in view. Durable state and long-term memory make the agent recoverable enough — and contextual enough — to trust with real work. Eventing and governed egress mean it can reach the world while every hop is authenticated and every credential stays out of its hands. And sandbox isolation means all of this runs contained by construction.

That is the design philosophy running through everything: **the platform absorbs the hard problems so agents don't have to.** Identity, delegation, policy, recovery, memory, and credential isolation are properties of the runtime, injected transparently — not libraries an agent author must correctly wire up. Security that depends on every developer getting it right is not security. Rosso's job is to make governed autonomy the thing you get for free — and to prove it, with a measurement discipline that quantifies what each layer costs, what it changes in agent behavior, and how the platform holds up under realistic load and failure.

## The horizon

Over the next few years, agents will move from assistants a person supervises to autonomous services that run continuously, remember across months, spawn other agents, and transact on our behalf across organizational boundaries. When that happens, the questions that decide whether the technology is trustworthy are exactly the ones Rosso is working on now: *Can you prove what an agent is, and what it's made of? Can you bound what it may do, for whom, for how long, and at what cost? Can a human — or their trusted surrogate — stay in the loop for what matters? Can it remember, adapt, and recover? Can it reach the world without ever holding the keys to it?*

We are building this in the open, on and alongside the emerging standards — A2A, MCP, SPIFFE — because a trust fabric for agents only works if it belongs to the whole ecosystem, not a single vendor. Rosso is our contribution to that foundation: the platform primitives for governed, zero-trust agent autonomy.
