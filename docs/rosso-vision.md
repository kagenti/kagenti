# Rosso — A Platform for Governed, Zero-Trust Agent Autonomy

> **Rosso is a research project first.** We build a production platform because ideas about autonomous agents only earn trust when they run — but the reason the project exists is to answer questions no one has settled yet: *What is an agent's identity, when the agent rewrites its own behavior at runtime? How do you lend authority to something non-deterministic and keep it bounded? What does it mean to govern an actor you cannot fully predict?* Everything below is organized around where we are pushing past the state of the art, and where we are honestly still building on it.

## The shift already underway

Software is learning to act on its own. AI agents no longer just answer questions — they plan, call tools, spend money, move data, and delegate to other agents to finish work that unfolds over minutes, hours, or days. The unit of computation is no longer a request that arrives and returns. It is an autonomous actor that reasons, remembers, and reaches out into the world on someone's behalf.

Our infrastructure was not built for this. The cloud-native stack assumes deterministic services with fixed identities, stable filesystems, short-lived requests, and permissions granted ahead of time. Agents violate every one of those assumptions. They are non-deterministic, long-running, stateful, and — most consequentially — they act with authority they were lent rather than authority they own. When an agent decides at runtime which tool to call and which data to touch, the guarantees that made cloud-native software safe to operate simply don't hold.

**Rosso exists to close that gap — and to close it with genuinely new ideas, not just new plumbing.** We are defining the platform primitives that autonomous agents need to run in production: provable identity, delegated authority, enforceable policy, durable memory, and governed reach — all by default, and all without asking agent developers to become security engineers. Where a strong open standard already exists — SPIFFE for workload identity, A2A for agent cards, RFC 8693 for token exchange — we build on it and say so plainly. Our contribution is what those standards do not yet reach: **binding an agent's authority to the integrity of what it is actually made of, making delegated authority credential-less by construction, and giving memory, cost, and governance the same first-class treatment identity has.**

### Where the frontier is

Not every primitive is equally novel, and we think saying so is what makes the novel parts credible. Three honest tiers run through this document:

- **Frontier — genuinely new.** Skill-bound identity (a tampered capability changes the agent's cryptographic identity, fail-closed), provenance-gated context (a fragment's lineage decides whether the model may act on it), and the surrogate approval agent. These are ideas we have not seen elsewhere; some are still designs on the bench.
- **Novel composition — new arrangement of known parts.** A single policy decision point fed by data lineage and budget; context assembly pushed out of the agent into a transparent governed stage; a zero-trust credential plane where the agent uses keys it can never read; a crash-recovery checkpoint that is also the agent's context-compaction artifact; signed identity-carrying events. The pieces exist; wiring them into one enforceable path for agents is the contribution.
- **Standards, hardened.** Runtime workload identity (SPIFFE/SPIRE), signed agent cards (A2A), just-in-time token exchange (RFC 8693), and durable recovery via event-sourcing + snapshots (Temporal/Orleans/Akka lineage). We are strengthening and integrating these, not reinventing them — and the frontier work is what we layer on top.
- **Open research bet.** The self-organizing, query-shaped memory layer (the "adaptive manifold") is an honest exploration, not a claim — adjacent to Drift-Adapter and memory-consolidation work, with a distinctive usage-driven angle we are still testing.

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

**Today:** Every agent is given a cryptographic identity rooted in the workload itself, not in a secret handed to it — built on SPIFFE/SPIRE workload identity and JWS-signed A2A agent cards. This is a strong, standard foundation, and we build on it directly.

**Horizon:** A *runtime attester* that observes the running workload and vouches for what it actually is — image, platform claims, integrity — not merely that a legitimate workload served the card. Today the standards prove *who is running*; they don't prove *how the card got here*. Closing that gap moves identity from asserted-once to continuously-true.

**The innovation:** *identity that keeps proving itself.* The novelty is not the SVID or the signed card — those are prior art we adopt — but pushing attestation from "a trusted workload is running" toward "the artifact this workload is serving is provably intact, right now," at the moment of every access decision.

### Skill & Supply-Chain Integrity — what the agent is made of

**Today:** Agents are increasingly assembled from skills, prompts, and capabilities pulled from external registries — a supply chain with no runtime integrity story. Build-time provenance (SLSA, Sigstore) proves a component was published through a trusted process; it says nothing about what a *running* agent has actually loaded.

**Horizon:** We fold a signature-verified skill-integrity digest into the agent's cryptographic identity itself — the SPIFFE identity path carries the skill hash — so a tampered or unverifiable skill yields a *different* identity, and the platform refuses to authorize it, fail-closed, before token exchange and before any tool call.

**The innovation — this is our flagship:** *a modified skill changes who the agent is.* Skill integrity stops being an advisory scan and becomes part of the workload's identity. This goes beyond build-time supply-chain provenance (which is static and off to the side) and beyond stock workload attestation (which proves who is running, not the integrity of the artifact it loaded) — turning supply-chain compromise from a detection problem into a property the trust model makes impossible. It is an early-stage design, and we are pursuing the upstream primitives it needs in the open.

### Delegation & Consent — acting for a user, with bounded authority

**Today:** When an agent acts on your behalf, it should carry exactly the authority you granted, for exactly as long as it needs it. Rosso implements just-in-time, user-scoped delegation on the OAuth token-exchange standard (RFC 8693) — an under-privileged agent obtains ephemeral, narrowly-scoped tokens at the moment it needs them, with the user's identity propagated down the agent-to-tool chain and re-scoped to least privilege at each hop.

**Horizon:** Authority that is minted for a *single intent*, provably scoped to it, and dissolves the instant the task completes — and a delegation path where *neither the agent nor the platform ever holds a standing credential for the user*, which the standard alone does not achieve (token exchange still relies on a party minting tokens that stand in for the user).

**The innovation — a composition, honestly:** the token-exchange mechanics are standard and we use them as such. The contribution is the *shape* of delegation for agents — reducing the window and blast radius toward per-intent, self-expiring authority, and driving toward genuinely credential-less delegation rather than merely well-scoped standing credentials.

---

## Pillar II — The Governance Plane

*What an agent may do, decided from full context, with a human where it counts.*

### Policy & Decision — one auditable verdict, from complete information

**Today:** Correct authorization for an agent depends on the caller, the callee, the user, and the task — far too rich for group-level roles. Rosso is building a fine-grained, context-aware policy layer where a single, auditable policy decision point renders every allow/deny verdict from complete information, rather than fragmenting authority across components that each decide with a partial view.

**Horizon:** Policy expressed in *human language*. The platform infers an agent's intended behavior and derives — then continuously audits — the fine-grained rules that match it, keeping intent and enforcement in sync as the agent fleet grows beyond what any security team could hand-author.

**The innovation:** *policy that authors and audits itself against inferred intent.* Rego, OPA, and central PDPs are established; the frontier is a control-plane agent that translates natural-language intent into enforceable rules and continuously checks the live rules back against that intent — treating drift between what we meant and what is enforced as a detectable, correctable condition.

### Human-in-the-Loop — from micro-management to delegated trust

We are redefining the human–agent relationship, shifting from active micro-management today to a future of autonomous decisions through delegated trust. In the near term, we are instrumenting the platform to continuously monitor long-running, event-driven, and asynchronous agents, enabling seamless human-in-the-loop interaction — such as mobile notifications — to safely verify high-risk actions and harvest direct feedback. For the long term, we are researching the **Agentic Avatar (Surrogate Agent)**, a personalized cognitive representation in code that replaces repetitive manual micro-approvals. By dynamically learning the user's habits, risk tolerances, and implicit intentions, this backend proxy safely auto-approves agent actions on the user's behalf — evolving the platform from a reactive notification system into a trusted, proactive digital representative.

**The innovation — frontier:** *the approver becomes an agent too.* Approval workflows and human-in-the-loop gates are well-trodden; the new idea is a learned surrogate that models one specific user's judgment and stands in for them on routine decisions — reserving the human for the genuinely novel or high-risk, and turning oversight from a bottleneck into something that scales with the agent fleet.

### Cost & Budget Governance — autonomy with a spending limit

**Today:** An autonomous agent that calls models in a loop can consume unbounded cost. Rosso enforces token and budget quotas at the platform layer — per team, per user, per session — with pre-request hard limits and an infrastructure-level circuit breaker that halts a runaway session before the bill arrives, not after.

**Horizon:** Budget becomes a first-class dimension of every authorization decision, enabling fair multi-tenant economics, FinOps chargeback, and cost as a governed resource rather than a surprise.

**The innovation — composition:** LLM gateways already meter and cap spend. The new angle is making budget a term in the *authorization* decision — the same PDP that decides *may this agent act* also decides *can it afford to* — so a session can be aborted mid-flight by the platform, not merely rate-limited at the gateway, and cost becomes a governance signal rather than a billing report.

### Data Security & Governance — context on every decision

**Today:** Data flows through an agent platform — in prompts, out through tool calls, across sessions and users — with no centralized governance. Rosso is building data-aware controls: classifying and tracing data lineage across agent trajectories, detecting breach and corruption risk, and feeding that context into policy decisions so an unsafe action can be blocked *before* it happens.

**Horizon:** The platform understands not just *whether* an action is allowed but *what data* it would move and where that data came from — closing the confused-deputy and exfiltration gaps that static controls cannot see.

**The innovation — composition:** classification and DLP exist; lineage catalogs exist. The new arrangement is feeding *live data lineage* — where this content originated, across which agents and sessions it has traveled — into a *pre-execution* authorization verdict, so an agent is stopped from moving data based on the data's own history, not just the action's shape.

### Quality & Evaluation — trusting the governors themselves

**Today:** As the platform's own governance components become autonomous — an agent that authors access policy, for instance — they need the same rigor we demand of the agents they govern. Rosso is building a quality framework of guardrails, adversarial testing, and evaluation (deterministic assertions alongside LLM- and agent-as-judge techniques) for its control-plane agents.

**Horizon:** Governed autonomy that is itself continuously validated — a platform whose safety properties are measured and regression-tested, not merely asserted.

---

## Pillar III — The Runtime Substrate

*How an agent lives, remembers, recovers, is fed, and reaches the world.*

### State, Session & Resiliency — durable, recoverable, portable

**Today:** Agents are stateful in ways cloud-native primitives never anticipated: they assume a stable filesystem, a single writer, an uninterrupted process. Production offers none of those. Rosso externalizes session state into a durable, append-only log so a session survives eviction, recovers after a crash with zero lost work, and can *move* between runtime instances.

**Horizon:** A serverless model for agents — scale-to-zero when idle, fast cold-start regardless of how long the conversation has run, and session mobility and self-healing recovery as native platform capabilities rather than bespoke integrations each team rebuilds.

**The innovation — composition, with two sharp edges.** Event-sourcing, snapshots, and workload mobility are textbook distributed-systems patterns (Temporal, Orleans, Akka), and we use them as such — we are not claiming to have invented durable recovery. Applying them to agents surfaces two ideas we *have not* seen elsewhere:

- **The checkpoint is semantically meaningful to the agent, not an opaque blob.** The same artifact that *compacts an agent's context window* — a summarized conversation the model can actually reason over — is the artifact that *truncates the replay log*. Context compaction and crash-recovery snapshotting become the same operation, so cold-start is O(1) in turns and the recovered state is native to the agent rather than a serialized memory dump.
- **A recovery-boundary failure taxonomy.** We classify agent failures by *where in the turn/inference/tool-call cycle the crash lands* — between turns, mid-inference, mid-tool-call, cross-component — because each boundary demands a different replay/idempotency guarantee. Fault taxonomies for agents exist; organizing them by recovery boundary to *derive the primitives a platform must provide* is the contribution.

### Long-Term Memory — the cognitive foundation

We are building the cognitive foundation for next-generation AI by transforming how autonomous agents remember, marrying immediate software systems with long-term neural design. In the near term, we are establishing **Long-Term Memory (LTM) as a platform-managed middleware layer** to continuously hydrate stateless agents with vital operational context at runtime. But stateful hydration is just the first step: our long-term research introduces **brain-inspired representation plasticity** to this layer, treating stored document vectors as mutable coordinates that warp, drift, and split under the gravity of live query streams. By uniting robust context plumbing with this adaptive memory manifold, we are creating a self-healing retrieval system that organically tracks shifting enterprise language without ever needing to touch the underlying, frozen LLM weights.

**The innovation — an exploratory research bet, stated honestly.** Two things here are already real elsewhere, and we build on them: hydrating an agent from an externalized memory layer (Mem0, Letta) and realigning a vector store without retraining the backbone model (Drift-Adapter, backward-compatible embeddings, query-drift compensation). What we are exploring beyond that prior art is the *driver*: memory that reorganizes **continuously and unsupervised, shaped by the live query distribution itself** — a usage-driven, Hebbian "what gets asked reshapes what is stored," rather than an offline drift-detection batch or an encoder upgrade. This is a research direction on the bench, not a shipped capability — but if it holds, memory becomes a self-organizing platform layer that tracks how an enterprise's language actually shifts, without ever touching the frozen model.

### Context Engineering — governing what enters the window

**Today:** An agent is only as good — and only as safe — as what lands in its context window: conversation history, tool outputs, retrieved documents, intermediate reasoning. Left to each agent, this is managed ad hoc, and an overstuffed or poisoned window degrades accuracy, inflates cost, and widens the injection surface. Rosso is building context assembly, compression, and pruning as a *transparent platform stage* wrapped around every model call — governed by policy with safety invariants, so the agent code never has to manage its own window.

**Horizon:** Context that is not just shaped but *governed* — every fragment entering the window carries provenance (where it came from, through which agents and sessions it traveled), and that provenance becomes an input to the authorization decision, not merely a line in a trace.

**The innovation — a composition with a frontier edge.** Pushing context assembly *out of the agent and into a transparent, governed request-path stage* is an architectural inversion of today's in-agent RAG and prompt frameworks — a novel placement, though each ingredient (retrieval middleware, redaction, prompt injection) exists in AI gateways. The genuinely new idea is **provenance-gated context**: feeding per-fragment lineage back into a runtime enforcement gate — filtering or denying a response because a context chunk's *source* lacks the caller's clearance. Observability tools capture context lineage for humans to read after the fact; closing that loop so lineage *drives the decision before the model acts* is, as far as we can find, not standard practice.

### Eventing & Governed Egress — communication and reach the agent can't abuse

**Today:** Agents talk to each other and reach out to the world, and both paths must be governed without rewriting the agent. Rosso treats inter-agent and tool traffic as signed, identity-carrying events, so no unauthorized party can impersonate an agent, tamper with a message, or publish where it shouldn't — enabling the long-running, asynchronous, approval-gated workflows synchronous calls can't support. On egress, a zero-trust credential plane keeps secrets only in an identity-aware broker that injects them at the network layer, keyed to the workload's identity.

**Horizon:** No component influenced by model output — not the agent, not its sandbox, not its logs — ever holds a raw credential. The agent gets to *use* a credential it can never *read*, for any destination, through one unified mechanism.

**The innovation — composition:** signed events and egress proxies are established individually. The contribution is the invariant that ties them together — *no component influenced by model output ever holds a raw secret* — enforced by injecting credentials at the network layer keyed to workload identity, so prompt injection cannot exfiltrate a key the agent was never given in the first place.

### Multi-Tenant Sandbox Isolation — safe execution by construction

**Today:** Autonomous code execution demands strong isolation. Rosso runs agents in isolated, per-tenant sandboxes with defense-in-depth — network, filesystem, and identity boundaries (Landlock, seccomp, network namespaces) — and a one-namespace-per-user model, so a compromised or misbehaving agent is contained by construction rather than by trust.

**Horizon:** Sandboxes that are disposable, instantly provisioned, and portable — a user's full working environment *teleported* into a governed remote runtime and torn down when done, with isolation strong enough that the platform can safely run untrusted agents from anywhere.

**The innovation — composition:** OS-level sandboxing is mature. The new arrangement is *teleportation* — packaging a user's local agent context (instructions, skills, settings) into a governed, isolated remote sandbox that runs with the platform's identity and credential guarantees — so the same session can move between a laptop and a hardened multi-tenant runtime without giving up isolation or governance.

### Extensible Plugin Pipeline — a governed extensibility model

**Today:** The controls above — identity, policy, guardrails, protocol handling — are not a monolith. Rosso exposes them as a versioned plugin pipeline with a stable contract, so guardrail, policy, and context-engineering capabilities from across the ecosystem compose into the agent's request path without each team building its own interception layer.

**Horizon:** An open extensibility standard for agent governance — a single, runtime-agnostic contract that lets the community contribute policy engines, guardrails, and context tooling that any Rosso deployment can adopt.

**The innovation — composition:** the value is not the plugin mechanism but the *decision discipline* it enforces — many components may enrich a request with context, but exactly one renders the verdict, no plugin can short-circuit it, and every decision leaves one auditable record. It turns an ad-hoc chain of interceptors into a governed decision pipeline with a single point of authority.

---

## What the primitives compose into: governed autonomy

Taken one at a time, some of these are features and some are frontier research. Taken together, they are something new: a platform on which an agent can be genuinely autonomous *and* genuinely governable at the same time. The innovation is not any single box — it is the insistence that identity, integrity, delegation, policy, cost, context, memory, and reach compose into *one enforceable path*, and the willingness to invent the missing pieces (skill-bound identity, provenance-gated context, the surrogate approver) rather than stop at what the standards already give us.

Attested identity means you know what you're trusting, down to the skills it's made of. Delegation and consent mean the agent acts with borrowed, bounded, revocable authority — and a human, or eventually that human's trusted surrogate, in the loop where it counts. Policy decides every action from full context, within a budget, with data lineage in view. Durable state and long-term memory make the agent recoverable enough — and contextual enough — to trust with real work. Eventing and governed egress mean it can reach the world while every hop is authenticated and every credential stays out of its hands. And sandbox isolation means all of this runs contained by construction.

That is the design philosophy running through everything: **the platform absorbs the hard problems so agents don't have to.** Identity, delegation, policy, recovery, memory, and credential isolation are properties of the runtime, injected transparently — not libraries an agent author must correctly wire up. Security that depends on every developer getting it right is not security. Rosso's job is to make governed autonomy the thing you get for free — and to prove it, with a measurement discipline that quantifies what each layer costs, what it changes in agent behavior, and how the platform holds up under realistic load and failure.

## The horizon

Over the next few years, agents will move from assistants a person supervises to autonomous services that run continuously, remember across months, spawn other agents, and transact on our behalf across organizational boundaries. When that happens, the questions that decide whether the technology is trustworthy are exactly the ones Rosso is working on now: *Can you prove what an agent is, and what it's made of? Can you bound what it may do, for whom, for how long, and at what cost? Can a human — or their trusted surrogate — stay in the loop for what matters? Can it remember, adapt, and recover? Can it reach the world without ever holding the keys to it?*

We are building this in the open, on and alongside the emerging standards — A2A, MCP, SPIFFE — because a trust fabric for agents only works if it belongs to the whole ecosystem, not a single vendor. Rosso is our contribution to that foundation: the platform primitives for governed, zero-trust agent autonomy.
