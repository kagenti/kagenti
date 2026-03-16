# Research Synthesis: From Static Context Files to Skills-Based Agent Architecture

**Date**: 2026-02-25
**Status**: Research synthesis / Design rationale

## Motivation

Every major coding agent recommends creating a repository-level context file (AGENTS.md, CLAUDE.md, CONVENTIONS.md). But recent empirical research questions whether this practice helps. This document synthesizes fourteen papers and resources from the 2025-2026 research timeline, connects their findings to Kagenti's existing skills-based architecture, and identifies the pattern that emerges: **minimal index + on-demand skills + CI enforcement + retrospective evolution + subagent context isolation**.

## Research Timeline

![Research Timeline](https://raw.githubusercontent.com/Ladas/blog-content/main/research-context-engineering/diagrams/research-timeline.png)

### Paper 1: "Agent READMEs: An Empirical Study" (Nov 2025)

- **ArXiv**: [2511.12884](https://arxiv.org/abs/2511.12884)
- **Scope**: 2,303 context files from 1,925 repositories across Claude Code, Codex, and Copilot
- **Contribution**: Descriptive taxonomy of what developers put in context files
- **Key finding**: Context files are widespread but their content varies wildly in structure and quality

### Paper 2: "On the Impact of AGENTS.md Files on Efficiency" (Jan 2026)

- **ArXiv**: [2601.20404](https://arxiv.org/abs/2601.20404)
- **Scope**: Codex (GPT-5.2) on 10 repos, 124 PRs
- **Contribution**: First quantitative efficiency measurement
- **Key findings**:
  - 28.64% median runtime reduction with AGENTS.md present
  - 16.58% median output token reduction
  - Comparable task completion rates
- **Limitations**: Only tested Codex, only small PRs (≤100 lines, ≤5 files), pre-filtered to files containing coding conventions + architecture + project description. Did not analyze which content types drove improvements.
- **Taxonomy categories**: Coding conventions/best practices, architecture/project structure, project description

### Paper 3: "Evaluating AGENTS.md: Are Repository-Level Context Files Helpful?" (Feb 13, 2026)

- **ArXiv**: [2602.11988](https://arxiv.org/abs/2602.11988)
- **Scope**: 4 agents (Claude Code, Codex ×2, Qwen Code), 4 models (Sonnet-4.5, GPT-5.2, GPT-5.1 mini, Qwen3-30b), 2 benchmarks (SWE-bench Lite 300 tasks, AGENTbench 138 tasks)
- **Contribution**: Most rigorous evaluation to date, with novel benchmark from repos that have real developer-committed context files
- **Key findings**:
  - LLM-generated context files: **-0.5% to -2% success rate, +20-23% cost**
  - Human-written context files: **+4% success rate, +19% cost**
  - Context files do NOT help agents find relevant files faster
  - Agents follow instructions faithfully (uv usage 160x, repo tools 50x when mentioned) but this compliance doesn't translate to more solved problems
  - Reasoning tokens increase 14-22% with context files present
  - When existing docs were removed, LLM-generated files improved by 2.7% — their entire value is as documentation substitute
- **Conclusion**: "Unnecessary requirements from context files make tasks harder, and human-written context files should describe only minimal requirements."
- **Gap identified**: "Motivates future work on principled ways to automatically generate concise, task-relevant guidance for coding agents."

### Paper 4: "Agent Skills for LLMs: Architecture, Acquisition, Security" (Feb 2026)

![Three Paradigms: Prompts to Tools to Skills](https://raw.githubusercontent.com/Ladas/blog-content/main/research-context-engineering/diagrams/three-paradigms.gif)

- **ArXiv**: [2602.12430](https://arxiv.org/abs/2602.12430)
- **Scope**: Survey of 62,000+ skill implementations, covering architecture, acquisition, deployment, and security
- **Contribution**: Formalizes skills as the next paradigm after prompts and tools. Directly addresses the gap Paper 3 identifies.
- **The three-paradigm evolution**:
  1. **Prompt engineering (2022-2023)**: Ephemeral, non-modular, hard to version
  2. **Tool use (2023-2024)**: Atomic function calls, execute-and-return, no procedural knowledge
  3. **Skill engineering (2025-present)**: Bundles of instructions, workflows, scripts, docs, metadata — dynamically loaded when relevant
- **Skill architecture** (SKILL.md with YAML frontmatter):
  - Level 1: Metadata only (~20-50 tokens) — always loaded for discovery
  - Level 2: Full procedural instructions — loaded when skill is triggered
  - Level 3: Technical appendices — loaded on-demand within skill execution
- **Key distinction**: "Tools execute and return results, whereas skills prepare the agent to solve a problem by injecting procedural knowledge."
- **Quantitative results**:
  - SAGE (RL + skills): 59% fewer tokens than baseline
  - Tool Search Tool: 85% token overhead reduction
  - Agentic Proposing: 91.6% on AIME 2025 with 30B model via compositional skill selection
  - SEAgent: 11.3% → 34.5% success on OSWorld
- **Critical warnings**:
  - **Phase transition**: Beyond critical library size, skill selection accuracy degrades sharply
  - **Security**: 26.1% of community skills contain vulnerabilities; scripts increase vulnerability 2.12× vs instruction-only
  - **Cross-platform portability**: Skills tied to specific agent platforms

### Paper 5: "Agentic Context Engineering (ACE)" (Oct 2025)

- **ArXiv**: [2510.04618](https://arxiv.org/abs/2510.04618)
- **Scope**: Framework for self-improving context through generation, reflection, and curation
- **Contribution**: Treats context as evolving playbooks with granular "bullets" (reusable strategies, domain concepts, failure modes)
- **Key findings**:
  - +10.6% improvement on agent tasks
  - +8.6% on finance domain
  - Context that self-improves through use outperforms static context
  - "Bullets" enable fine-grained retrieval and incremental adaptation

### Paper 6: "Meta Context Engineering via Agentic Skill Evolution" (Jan 2026)

- **ArXiv**: [2601.21557](https://arxiv.org/abs/2601.21557)
- **Scope**: Bi-level optimization framework where skills themselves evolve through an evolutionary process
- **Contribution**: Supersedes static context engineering by co-evolving CE skills and context artifacts
- **Key mechanism**: A meta-agent iteratively refines skills via "agentic crossover" — an LLM-driven operator that synthesizes new skills by reasoning across task specifications, historical trajectories, and performance metrics
- **Key findings**:
  - **5.6-53.8% relative improvement** over SOTA agentic CE methods (mean 16.9%)
  - Evaluated across 5 domains (finance, chemistry, medicine, law, AI safety) with 4 LLMs
  - MCE learns to produce context of suitable length per task (1.5K tokens for finance vs 86K for chemistry), contrasting with static approaches that bloat or under-specify uniformly
  - Superior transferability: when transferring to smaller models, MCE shows 17.1-43.4% degradation vs ACE's 23.6-48.3%
  - At comparable context length (~1.5K tokens), MCE achieves 73% vs ACE's 65%
- **Relevance to Kagenti**: This is the academic formalization of what `skills:retrospective` does — evolving skills based on session experience. The "agentic crossover" maps to retrospective's pattern of analyzing session failures, identifying skill gaps, and creating/refining skills.

### Paper 7: "Contextual Experience Replay (CER)" (Jun 2025)

- **ArXiv**: [2506.06698](https://arxiv.org/abs/2506.06698) — ACL 2025
- **Scope**: Training-free framework for agent self-improvement within context windows
- **Contribution**: Agents accumulate and synthesize past experiences into dynamic memory, retrieving relevant knowledge for new tasks
- **Key findings**:
  - 51% relative improvement over GPT-4o baseline on WebArena
  - Competitive with tree search methods at much lower token cost
  - Works in both online (learn → solve → learn) and offline (learn from traces → solve) settings
- **Relevance to Kagenti**: Maps to session analytics scanning — extracting patterns from past sessions to improve future ones

### Paper 8: "SAGE: RL for Self-Improving Agent with Skill Library" (Dec 2025)

- **ArXiv**: [2512.17102](https://arxiv.org/abs/2512.17102)
- **Scope**: RL-based approach to skill library self-improvement
- **Contribution**: Transforms interaction experiences into reusable skills via RL (not just prompting), achieving consistent skill library growth
- **Key findings**:
  - 59% fewer tokens than baseline GRPO
  - 8.9% task goal completion improvement
  - Skills condensing complex action sequences into reusable operations
- **Relevance to Kagenti**: Validates that experience → skill extraction → reuse is a sound loop. Kagenti does this via retrospective + skills:scan rather than RL.

### Paper 9: "Self-Evolving Agents Survey" (Aug 2025)

- **ArXiv**: [2507.21046](https://arxiv.org/abs/2507.21046)
- **Scope**: Comprehensive survey of agents that adapt their perception, reasoning, and actions
- **Contribution**: Taxonomy of self-evolution mechanisms: experience accumulation, skill abstraction, knowledge refinement (add/update/delete/combine operations)
- **Key insight**: Static agents hit a "critical bottleneck" in open-ended environments. Self-evolution through structured experience libraries is the path forward.

### Paper 10: "Mem^p: Exploring Agent Procedural Memory" (Aug 2025)

- **ArXiv**: [2508.06433](https://arxiv.org/abs/2508.06433)
- **Scope**: Distilling agent trajectories into both fine-grained step-by-step instructions and higher-level script-like abstractions
- **Contribution**: Dynamic regimen that continuously updates, corrects, and deprecates procedural memory contents
- **Key findings**:
  - Agents achieve steadily higher success rates as memory repository is refined
  - Procedural memory built from a stronger model retains value when migrated to weaker models
- **Relevance to Kagenti**: Skills ARE procedural memory. The "update, correct, deprecate" lifecycle maps directly to retrospective's add/update/delete skill operations.

### Paper 11: "Truly Self-Improving Agents Require Intrinsic Metacognitive Learning" (ICML 2025)

- **Source**: [OpenReview](https://openreview.net/forum?id=4KhDd0Ozqe)
- **Contribution**: Argues that effective self-improvement requires three components: metacognitive knowledge (knowing what you know), metacognitive planning (adapting learning strategies), metacognitive evaluation (assessing own performance)
- **Key insight**: Single-agent reflexion falls into confirmation bias and repeated errors. External evaluation mechanisms are needed.
- **Relevance to Kagenti**: The retrospective skill provides the metacognitive evaluation layer. Session analytics provide metacognitive knowledge. Skills:scan provides metacognitive planning.

### Paper 12: "Codified Context: Infrastructure for AI Agents in a Complex Codebase" (Feb 2026)

- **ArXiv**: [2602.20478](https://arxiv.org/abs/2602.20478)
- **Scope**: Practitioner report from building a 108,000-line C# distributed system with AI agents across 283 development sessions over 70 days
- **Contribution**: The most detailed practitioner validation of tiered context architecture. Three-tier system: hot-memory constitution (always loaded), 19 specialized domain-expert agents (invoked per task), cold-memory knowledge base (retrieved on demand via MCP)
- **The three tiers**:
  - **Tier 1 — Constitution (hot memory)**: ~660 lines of Markdown (0.6% of codebase), always loaded. Contains code standards, build commands, architectural patterns, orchestration protocols (trigger tables routing tasks to specialized agents). Design constraint: must be concise enough for every session.
  - **Tier 2 — Specialized agents**: 19 agent specification files (115-1,233 lines each, ~9,300 lines total = 8.6% of codebase). Over half of each specification is project-domain knowledge (codebase facts, formulas, failure modes) rather than behavioral instructions. Created emergence-driven: "If debugging a particular domain consumed an extended session without resolution, it was faster to create a specialized agent and restart."
  - **Tier 3 — Knowledge base (cold memory)**: 34 Markdown documents (~16,250 lines = 15% of codebase). Written for AI consumption. Retrieved on-demand via MCP server with 5 search tools. Single subsystem per document for targeted retrieval.
- **Key quantitative findings**:
  - Total context infrastructure: 26,200 lines (24.2% of codebase)
  - 80%+ of human prompts ≤100 words (pre-loaded context reduces prompt length)
  - 57% of agent invocations used project-specific specialists (vs 43% built-in tools)
  - Save system spec (283 lines, most-referenced at 74 sessions): zero save-related bugs across four weeks
  - Maintenance: ~5 min/session + 30-45 min biweekly review
- **Six practitioner guidelines**:
  - G1: A basic constitution does heavy lifting (start early, prevents entire class of mistakes)
  - G2: Let the planner gather context (run planning agent before implementation)
  - G3: Route automatically or forget constantly (trigger tables + search)
  - G4: If you explained it twice, write it down
  - G5: When in doubt, create an agent and restart (creating specialist beats extended unguided debugging)
  - G6: Stale specs mislead (agents trust documentation absolutely; out-of-date specs cause silent failures)
- **Critical warning**: "Agents trust documentation absolutely; out-of-date specs cause silent failures." Stale specifications are the primary failure mode — syntactically correct code with incorrect logic.
- **Relevance to Kagenti**: This is the closest practitioner analog to Kagenti's architecture: Tier 1 = CLAUDE.md, Tier 2 = skills, Tier 3 = docs/. Key differences: Kagenti has 85+ skills vs 19 agents; Kagenti uses CI enforcement; Kagenti has retrospective evolution.

### Paper 13: "ContextBench: A Benchmark for Context Retrieval in Coding Agents" (Feb 2026)

- **ArXiv**: [2602.05892](https://arxiv.org/abs/2602.05892)
- **Scope**: Process-oriented evaluation of how agents retrieve context: 1,136 tasks from 66 repos across 8 languages, with human-verified gold contexts totaling 522,115 lines
- **Contribution**: Instead of "did the agent solve it?" asks "did the agent retrieve the right context to solve it?" Provides file/block/line-level retrieval metrics.
- **Key findings**:
  - "Sophisticated scaffolding does not necessarily improve context retrieval" — simple shell-based agent matched or beat graph-based retrieval, semantic embeddings, specialized interfaces
  - Claude Sonnet 4.5 achieved best line-level F1 (0.530) with balanced retrieval strategy (14 steps, ~30 lines/step)
  - Block-level F1 scores all below 0.45 — "state-of-the-art LLMs still face challenges in retrieving effective context"
  - **Context usage drop** is the critical bottleneck: agents retrieve context but fail to use it during patch generation. GPT-5/Claude lose 18-19% of retrieved context; Gemini/Devstral lose 43%+
  - Early gold-context discovery (efficiency score) predicts better outcomes
  - Balanced retrieval granularity outperforms extremes (too few/too many retrieval steps both underperform)
- **Effective strategies**: balanced granularity, early discovery, precision-conscious expansion, context consolidation
- **Ineffective strategies**: over-engineering, aggressive expansion, context abandonment, unbalanced retrieval
- **Relevance to Kagenti**: Validates the subagent pattern — the "context usage drop" problem (agents retrieve context but don't use it) is exactly what happens when verbose context files dump information the agent doesn't need for the current task. On-demand skills solve this by loading only task-relevant context. Also validates that simple approaches (shell commands) can match sophisticated retrieval.

### Paper 14: "Agents of Chaos" (Feb 2026)

- **ArXiv**: [2602.20021](https://arxiv.org/abs/2602.20021)
- **Scope**: Red-teaming study of autonomous agents with persistent memory, email, Discord, file systems, and shell execution. 20 AI researchers tested over two weeks under benign and adversarial conditions.
- **Contribution**: Documents 11 case studies of security failures in deployed agent systems
- **Vulnerability categories**:
  - Unauthorized compliance with non-owners
  - Sensitive information disclosure
  - Destructive system-level actions
  - Denial-of-service conditions
  - Uncontrolled resource consumption
  - Identity spoofing
  - **Cross-agent propagation of unsafe practices**
  - Partial system takeover
  - Agents reporting task completion while system state contradicts
- **Relevance to Kagenti**: Directly validates the security concerns in Paper 4 (26.1% vulnerable skills) and motivates Kagenti's approach:
  - **First-party skills only**: Cross-agent propagation of unsafe practices is the multi-agent version of supply-chain attacks on skill libraries
  - **settings.json permission scoping**: Auto-approve sandbox operations, require approval for management operations — addresses unauthorized compliance and destructive actions
  - **CI enforcement over context prescription**: Agents following instructions blindly (Paper 3) + agents complying with unauthorized requests (Paper 14) = instructions are an attack surface. CI hooks can't be socially engineered.
  - **Subagent isolation**: Limits blast radius — a compromised subagent can't access main agent's full context or tool permissions
  - **Stale spec danger**: Paper 12's finding that "agents trust documentation absolutely" combined with Paper 14's identity spoofing means malicious context injected via stale docs could cause silent failures

### Additional references

- [Martin Fowler: "Context Engineering for Coding Agents"](https://martinfowler.com/articles/exploring-gen-ai/context-engineering-coding-agents.html) — practical overview, identifies skills as newest paradigm
- [arXiv:2507.13334 "Survey of Context Engineering for LLMs"](https://arxiv.org/abs/2507.13334) — formal taxonomy (1,400+ papers surveyed)
- [arXiv:2510.21413 "Context Engineering for AI Agents in Open-Source Software"](https://arxiv.org/abs/2510.21413) — 4.7% of engineered OSS repos contain agent config files
- [arXiv:2601.18341 "Agentic Much? Adoption of Coding Agents on GitHub"](https://arxiv.org/abs/2601.18341) — 15.85-22.60% adoption rate across 129,134 projects
- [JetBrains Research: "Smarter Context Management for LLM-Powered Agents"](https://blog.jetbrains.com/research/2025/12/efficient-context-management/) — context rot and degradation analysis
- [Prime Intellect: "Recursive Language Models"](https://www.primeintellect.ai/blog/rlm) — models that proactively delegate context to sub-LLMs
- [arXiv:2602.16653 "Agent Skill Framework for Small Language Models"](https://arxiv.org/abs/2602.16653) — skill deployment challenges with smaller models
- [Codified Context GitHub repo](https://github.com/arisvas4/codified-context-infrastructure) — open-source three-tier architecture implementation

## The Pattern That Emerges

![Verbose Context Hurts Agent Performance](https://raw.githubusercontent.com/Ladas/blog-content/main/research-context-engineering/diagrams/the-problem.png)

### What the papers collectively demonstrate

1. **Verbose static context hurts.** LLM-generated context files reduce success rates while increasing cost (Paper 3). The mechanism: agents spend tokens on compliance and over-exploration instead of problem-solving.

2. **Minimal human-written context helps marginally.** Developer-authored files that add unique signal (not duplicating docs) show small improvements (Paper 3). The key is editorial judgment — include what matters, omit what doesn't.

3. **On-demand loading solves the cost problem.** Skills with progressive disclosure (Paper 4) achieve 59-85% token reductions versus baseline. Load knowledge when needed, not upfront.

4. **CI enforcement beats prescription.** Paper 3 shows agents dutifully follow instructions like "use uv" and "run pre-commit" (160x and 50x usage increase) at the cost of 20% more tokens — without solving more problems. If CI hooks enforce these automatically, the agent doesn't need to be told.

5. **Skills that evolve through use outperform static skills.** Meta Context Engineering (Paper 6) achieves 5.6-53.8% improvement by evolving skills via retrospective analysis. Static skills are a local optimum.

6. **Subagent context isolation prevents context rot.** Research consistently shows agent performance degrades as context fills (context rot). Delegating analysis to subagents with isolated context windows preserves main-agent reasoning quality.

7. **Tiered knowledge architecture scales where single files don't.** The Codified Context practitioner report (Paper 12) independently discovered the same three-tier pattern: hot memory (always loaded, ~660 lines), specialists (invoked per task, 19 agents), cold memory (retrieved on demand, 34 docs). A single manifest works for ~1,000-line prototypes but fails at 100,000+ lines. Their 283-session validation shows zero bugs in well-specified subsystems.

8. **Context retrieval is necessary but not sufficient.** ContextBench (Paper 13) shows agents lose 18-43% of retrieved context between retrieval and patch generation ("usage drop"). Loading context into the window doesn't guarantee the agent will use it. This further argues for on-demand, task-scoped context over verbose upfront loading.

9. **Context files are an attack surface.** Agents of Chaos (Paper 14) documents cross-agent propagation of unsafe practices, identity spoofing, and unauthorized compliance. Combined with Paper 12's finding that "agents trust documentation absolutely," context files become a vector for silent failures — both accidental (stale specs) and adversarial (injected instructions).

10. **Simple retrieval matches sophisticated scaffolding.** ContextBench (Paper 13) found that a simple shell-based agent matched or beat agents with graph-based retrieval, semantic embeddings, and specialized interfaces. Over-engineering context retrieval is counterproductive — balanced granularity and context consolidation matter more.

### The architecture

![Kagenti Context Architecture](https://raw.githubusercontent.com/Ladas/blog-content/main/research-context-engineering/diagrams/kagenti-architecture.gif)

**CLAUDE.md** (~200 lines, mostly tables and links)
Minimal index: project overview, key commands, pointers to skills and docs. No verbose rules.

  |-- **Skills (85+)** — On-demand loading via Skill tool + retrospective loop *(Level 2 knowledge)*
  |-- **Docs** — On-demand loading via Read tool *(Level 3 knowledge)*
  |-- **CI/Hooks** — pre-commit, linters, tests, sign-off check *(Enforcement, no context cost)*
  |-- **Subagents** — Isolated context windows for log analysis, return only summaries *(Context isolation)*

### Why this works (mapped to paper findings)

| Problem (from papers) | Solution in this architecture |
|---|---|
| Verbose context increases reasoning tokens +22% (Paper 3) | CLAUDE.md is a minimal index; details loaded on-demand |
| Codebase overviews don't help find files (Paper 3) | No codebase overview in CLAUDE.md; agents explore naturally |
| LLM-generated context duplicates docs (Paper 3) | CLAUDE.md links to docs instead of inlining them |
| Instruction compliance costs tokens without improving outcomes (Paper 3) | CI hooks enforce conventions; agent isn't told to comply |
| Context window pollution causes exponential cost growth | Context Budget rules + subagent isolation pattern |
| Phase transition at large skill libraries (Paper 4) | Monitor routing accuracy as library grows past 85+ skills |
| 26.1% community skills contain vulnerabilities (Paper 4) | First-party skills only; no community skill marketplace |
| Static context is a local optimum (Paper 6) | Retrospective skill evolves skills through session experience |
| Single-agent reflexion has confirmation bias (Paper 11) | External evaluation via CI feedback + session analytics |
| Context rot degrades performance over long sessions | Subagents with isolated context windows handle analysis |
| Single manifests don't scale past ~1K lines (Paper 12) | Tiered: CLAUDE.md (hot) + skills (specialist) + docs (cold) |
| Agents trust documentation absolutely (Paper 12) | Retrospective detects stale skills; CI validates correctness |
| Context usage drop: retrieved but unused context (Paper 13) | Skills load only task-scoped context; not a haystack |
| Over-engineered retrieval underperforms simple approaches (Paper 13) | Skills are simple Markdown files invoked by name, not semantic search |
| Context files are an attack surface (Paper 14) | First-party skills + settings.json permissions + CI enforcement |
| Cross-agent propagation of unsafe practices (Paper 14) | Subagent isolation limits blast radius |

## Kagenti's Implementation vs Paper 4's Architecture

| Paper 4 Concept | Kagenti Implementation |
|---|---|
| SKILL.md with YAML frontmatter | `.claude/skills/*/SKILL.md` — same format |
| Level 1: Metadata (~20-50 tokens) | Skill names + descriptions in system prompt |
| Level 2: Full instructions on trigger | `Skill` tool invocation loads full SKILL.md |
| Level 3: Appendices on-demand | Skills reference docs/, charts/, scripts/ as needed |
| Skill routing | System prompt lists available skills; agent or user selects |
| Smart routers | Parent skills (e.g., `tdd:`, `rca:`) auto-select sub-skills |
| Security governance | First-party only; settings.json permission scoping |
| Compilation (multi-agent → single-agent) | Skills replace what would be multi-agent orchestration |

## Subagent Context Isolation Pattern

![Subagent Context Isolation](https://raw.githubusercontent.com/Ladas/blog-content/main/research-context-engineering/diagrams/subagent-isolation.gif)

### The problem

Research identifies "context rot" — agent performance degrades as the context window fills, even when within technical token limits. In Kagenti's domain (Kubernetes, CI, Helm), a single `kubectl get pods -A` dumps 50-200 lines. A CI log failure analysis can be 1000+ lines. Each line, once in context, is re-read on every subsequent turn, causing exponential cost growth.

### The solution: main agent sees only return codes and summaries

Kagenti implements a hierarchical context architecture across 33+ skills:

**Main Agent Context (clean)**

  1. Executes: `command > $LOG_DIR/output.log 2>&1; echo "EXIT:$?"`
     Only "EXIT:0" or "EXIT:1" enters main context

  2. Spawns: `Task(subagent_type='Explore')`
     Subagent reads log in its OWN isolated context
     Subagent uses Grep with -C 3 (not full file reads)
     Returns: "First error: X in test Y, line Z"
     Only this summary enters main context

  3. Main agent reasons on summaries, not raw output

### How this maps to research

| Research Concept | Kagenti Implementation |
|---|---|
| **Context Folding** (FoldGRPO, Oct 2025): Replace intermediate steps with concise summaries, 10× smaller active context | Subagents fold verbose output into summaries; main context sees only return codes |
| **Manus's "Share memory by communicating"**: Each sub-agent has isolated context, communicates results | Each `Task(subagent_type='Explore')` has its own context window; returns summary to main |
| **Google ADK "scope by default"**: Every model call sees minimum required context | Subagents receive only: log file path + specific question (e.g., "find first FAILED") |
| **Context Budgets with Inheritance**: Subagents inherit portion of parent budget | Enforced by CLAUDE.md Rules 1-3 + `context-safe.sh` helper functions |
| **Recursive Language Models** (Prime Intellect): Models proactively delegate context to sub-LLMs | Exactly what Kagenti does — main agent delegates log analysis to sub-LLMs |

### The cost math

Without isolation (naive):
- `kubectl get pods -A` = 100 lines × N subsequent turns = 100N lines processed
- CI log analysis = 1000 lines × N turns = 1000N lines processed
- Total context cost grows linearly per command, multiplicatively across turns

With isolation (Kagenti):
- `EXIT:0` = 1 line × N turns = N lines processed
- Subagent summary = 3 lines × N turns = 3N lines processed
- Subagent's own cost = 1000 lines × 1 turn = 1000 lines (amortized, not re-read)
- Total: 4N + 1000 vs 1100N — at N=10 turns, this is 1040 vs 11,000 lines

### Skills that implement this pattern

Every operational skill (tdd:*, rca:*, k8s:*, ci:*, helm:*, openshift:*, kagenti:*) follows the same pattern:
1. Redirect output to `/tmp/kagenti/<category>/$WORKTREE/<component>.log`
2. Return exit code or "OK"/"FAIL" to main context
3. Use `Task(subagent_type='Explore')` to analyze logs
4. Subagent uses `Grep` with context (`-C 3`) and `head_limit` — never reads entire files
5. Subagent returns concise summary: first error, test name, assertion, 2-3 context lines

The helper library `context-safe.sh` provides reusable functions: `run_captured`, `run_quiet`, `kube_captured`, `run_tests`, and `cleanup_logs`.

## Retrospective Skill Evolution: Kagenti's Self-Improving Loop

### The academic precedent

Multiple papers converge on the same finding: skills/context that evolve through use outperform static versions.

| Paper | Mechanism | Result |
|---|---|---|
| ACE (Paper 5) | "Bullets" — reusable strategies accumulated through reflection | +10.6% on agent tasks |
| MCE (Paper 6) | Agentic crossover — evolutionary operator synthesizing skills from trajectories | +16.9% mean improvement |
| SAGE (Paper 8) | RL-based skill library growth from interaction experiences | 59% fewer tokens |
| CER (Paper 7) | Experience replay — accumulating past session knowledge | +51% over GPT-4o baseline |
| Mem^p (Paper 10) | Procedural memory that continuously updates, corrects, deprecates | Steadily increasing success rates |
| Self-Evolving Agents (Paper 9) | Knowledge refinement: add/update/delete/combine operations | Taxonomy of evolution patterns |

### Kagenti's implementation: the retrospective loop

Kagenti already implements a skill evolution loop through three interconnected skills:

**`skills:retrospective`** (the evolution step):
1. Analyze session: review commands, debugging cycles, repeated lookups, missing workflows
2. Analyze commit history: identify revert/fix chains, blind paths, wasted iterations (target 3:1 feature:fix ratio)
3. Skill inventory review: check for duplicates, verify best practices, identify refactoring candidates
4. Create plan: formal plan document for skill updates, refactors, deletions
5. Execute with approval: refactors first, then updates, then new skills; checkpoint after major changes

This maps to Paper 6's "agentic crossover" — reasoning across task specifications, historical trajectories, and performance metrics to synthesize improved skills.

**`skills:scan`** (the audit step):
- Gap analysis: compare existing skills against actual tech stack
- Content quality review: actionability, length, freshness, cross-links
- Usefulness assessment: rate each skill 1-5 based on decision trees, commands, troubleshooting coverage
- Connection analysis: outgoing refs, incoming refs, broken refs, orphaned skills

This maps to Paper 11's "metacognitive knowledge" — the system knowing what it knows and where the gaps are.

**`session:extract` + `session:summary`** (the observation step):
- Extract session analytics from GitHub PR/issue comments
- Track tokens, costs, tool calls, duration across sessions
- Generate aggregated dashboards for trend analysis

This maps to Paper 7's "experience replay" — structured access to past interaction data.

### The evolution lifecycle

![Retrospective Skill Evolution Loop](https://raw.githubusercontent.com/Ladas/blog-content/main/research-context-engineering/diagrams/retrospective-loop.gif)

**Session N** — Agent uses skills, succeeds/fails, session ends
  |
  v
**session:extract** — Extract analytics, patterns, failure modes from session N's PR comments / JSONL logs
  |
  v
**skills:retrospective** — Phase 1: What went wrong? Phase 2: Which skills need updating? Phase 3: Plan (add/update/delete/combine). Phase 4: Execute skill changes
  |
  v
**skills:scan** — Validate: frontmatter, naming, cross-refs. Quality: actionability, freshness, usefulness. Gaps: what the tech stack needs that skills lack
  |
  v
**Session N+1** — Agent uses improved skills (loop back to Session N)

### What Paper 6 (MCE) adds that Kagenti doesn't yet do

MCE's key innovation is **automated evolutionary selection**: the meta-agent runs multiple skill variants, measures their performance on validation tasks, and retains the better one via (1+1)-Evolution Strategy. Kagenti's retrospective is human-in-the-loop (developer reviews plan before execution).

MCE also learns to produce **context of suitable length per task** (1.5K tokens for simple tasks, 86K for complex ones). Kagenti's skills have static length — the retrospective could incorporate a quality signal about whether skills are too verbose or too sparse for their actual use patterns.

### Connecting to worktrees

Kagenti's worktree workflow provides natural isolation for skill evolution experiments:

1. **Skill development happens in worktrees** (`skills:write` enforces a worktree gate)
2. **Each worktree has its own session log directory** (`/tmp/kagenti/tdd/$WORKTREE/`)
3. **Worktrees can test skill changes** against real deployments before merging
4. **Multiple worktrees enable parallel skill experiments** — different skill variants in different worktrees, measuring outcomes independently

This maps to MCE's evaluation framework: run variants, measure performance, keep the winner. Worktrees provide the isolation infrastructure; session analytics provide the measurement; retrospective provides the evolution step.

### Connecting to existing plans

The `docs/plans/` directory shows the pattern in action:

- `2026-02-15-session-metadata-analytics-design.md` — designed the session analytics system
- `2026-02-15-session-metadata-analytics-impl.md` — implemented it
- `2026-02-23-sandbox-agent-research.md` — comprehensive research synthesis (7 projects, 18 capabilities, 8 diagrams)
- `2026-02-24-sandbox-agent-implementation-passover.md` — implementation roadmap with capability dependencies

Each plan is itself an artifact of the retrospective process: identify a gap, research the landscape, design a solution, implement in a worktree, merge when validated.

## Kagenti vs Codified Context: Two Independent Implementations of the Same Architecture

![Codified Context vs Kagenti Comparison](https://raw.githubusercontent.com/Ladas/blog-content/main/research-context-engineering/diagrams/codified-context-comparison.png)

Paper 12 ("Codified Context") is the closest practitioner analog to Kagenti's architecture. Both systems were developed independently and converged on the same tiered pattern.

| Dimension | Codified Context (Paper 12) | Kagenti |
|---|---|---|
| **Hot memory** | Constitution (~660 lines, always loaded) | CLAUDE.md (~213 lines, always loaded) |
| **Specialists** | 19 agent specs (115-1,233 lines each) | 85+ skill files (80-300 lines each) |
| **Cold memory** | 34 knowledge base docs via MCP | docs/ directory via Read tool |
| **Routing** | Trigger tables in constitution | Skill names/descriptions in system prompt |
| **Retrieval** | MCP server with 5 search tools | Skill tool + Glob/Grep/Read |
| **Scale** | 108K lines C#, 1 developer, 70 days | Multi-developer platform, ongoing |
| **Evolution** | Manual updates + drift detector | Retrospective skill + session analytics |
| **Enforcement** | None (trust-based) | CI hooks + pre-commit + settings.json |
| **Context isolation** | Not discussed | Subagent pattern (33+ skills) |

### Where Kagenti goes further

1. **CI enforcement**: Paper 12 relies entirely on documentation being correct ("agents trust documentation absolutely"). Kagenti adds CI as a safety net — if a stale skill recommends the wrong approach, pre-commit hooks and tests catch the error. Paper 12 reports stale specs as their "primary failure mode"; Kagenti's CI layer mitigates this.

2. **Retrospective evolution**: Paper 12's drift detector checks if source files changed without spec updates. Kagenti's `skills:retrospective` goes deeper — it analyzes session failures, identifies skill gaps, and proposes skill improvements. This maps to Paper 6's evolutionary approach.

3. **Subagent context isolation**: Paper 12 doesn't discuss context window management within sessions. Kagenti's subagent pattern keeps the main context clean (only return codes and summaries), delegating verbose log analysis to isolated subagents.

4. **Scale of specialists**: Paper 12 has 19 agents averaging 488 lines each. Kagenti has 85+ skills averaging ~150 lines each. Kagenti's skills are more granular and modular, which may help with the phase transition problem (Paper 4) — smaller routing decisions are easier than choosing among 19 large specialists.

### Where Codified Context goes further

1. **Embedded domain knowledge**: Paper 12 reports that "over half of each specification's content is project-domain knowledge (codebase facts, formulas, failure modes) rather than behavioral instructions." Kagenti's skills are more procedurally focused (how-to workflows) with less embedded domain knowledge. Paper 12's approach may produce more reliable outputs in complex domains.

2. **Emergence-driven creation**: Paper 12's heuristic — "if debugging a particular domain consumed an extended session without resolution, create a specialized agent and restart" — is a concrete trigger for skill creation. Kagenti's retrospective identifies gaps but doesn't have this specific "restart" pattern.

3. **Knowledge-to-code ratio tracking**: Paper 12 tracks their 24.2% ratio as a health metric. Kagenti doesn't track this, but it could be a useful signal for when skills need expansion.

4. **Explicit maintenance cadence**: 5 min/session + 30-45 min biweekly review. Kagenti's retrospective is ad-hoc rather than scheduled.

## Context Retrieval vs Context Loading: Lessons from ContextBench

![Context Usage Drop](https://raw.githubusercontent.com/Ladas/blog-content/main/research-context-engineering/diagrams/context-usage-drop.png)

Paper 13 (ContextBench) provides a critical distinction: it's not enough to *retrieve* context — agents must *use* it during reasoning. Their "context usage drop" metric shows 18-43% of retrieved context is abandoned between retrieval and patch generation.

This validates the skills approach over AGENTS.md in a way the other papers don't:

- **AGENTS.md loads everything upfront** → agent has a haystack of context → must decide what's relevant → high usage drop
- **Skills load task-scoped context on demand** → agent has only what it asked for → lower usage drop

ContextBench also found that balanced retrieval granularity (Claude Sonnet's 14 steps, ~30 lines/step) outperforms both aggressive expansion (GPT-5's 6 steps, 119 lines/step) and fine-grained probing (Devstral's 22 steps, 12 lines/step). This maps to skills design: skills should be ~80-300 lines (not 1,000+), loaded when relevant (not all at once), and focused on one domain (not comprehensive).

## Security: Context Files as Attack Surface

![Security: Attack Chain vs Defense Layers](https://raw.githubusercontent.com/Ladas/blog-content/main/research-context-engineering/diagrams/security-chain.png)

Paper 14 ("Agents of Chaos") combined with Paper 12's finding that "agents trust documentation absolutely" creates a concerning picture:

Stale or malicious context file
  --> Agent trusts it absolutely (Paper 12)
  --> Agent follows instructions faithfully (Paper 3, 160x compliance)
  --> Agent executes destructive actions (Paper 14)
  --> Cross-agent propagation amplifies impact (Paper 14)

### Kagenti's defense layers

| Attack vector (from Paper 14) | Kagenti mitigation |
|---|---|
| Unauthorized compliance with non-owners | settings.json permission scoping: sandbox vs management operations |
| Destructive system-level actions | Auto-approve only for Kind clusters, /tmp/; management cluster requires approval |
| Cross-agent propagation | Subagent isolation: each subagent has limited scope and tools |
| Identity spoofing | First-party skills only; no community marketplace |
| Stale specs causing silent failures | Retrospective + CI: stale skills cause test failures caught by CI |
| Context injection via documentation | skills:scan validates skill content and cross-references |

### The CI-as-enforcement advantage for security

Paper 3 shows agents follow context file instructions with 160x compliance. Paper 14 shows this compliance extends to malicious instructions. This means context files are a liability: every instruction in CLAUDE.md or AGENTS.md is a potential vector.

CI enforcement inverts this: instead of telling the agent "don't do X" (which can be overridden by injection), CI *prevents* X from succeeding. Pre-commit hooks can't be socially engineered. Test suites don't comply with unauthorized requests. This is defense-in-depth applied to agent architecture.

## What Kagenti Does That Papers Don't Study

### CI as enforcement layer

No paper explicitly benchmarks "CI enforcement vs context file prescription." Paper 3 demonstrates the problem (agents waste tokens on compliance) but doesn't test the alternative. Kagenti's approach:

- `pre-commit` hooks catch formatting, linting, sign-off automatically
- Test suites validate correctness on push
- CI pipeline runs E2E tests, Helm validation, security scanning
- Agent gets feedback through exit codes, not upfront instructions

This removes an entire category of context file content ("use black for formatting", "run mypy", "follow PEP 8") that Paper 3 shows costs tokens without helping.

### Context Budget as a meta-rule

CLAUDE.md's Context Budget section (Rules 1-3) is prescriptive — the kind of content Paper 3 says hurts. But it's a justified exception: these rules control the cost of *all other context*, making them net-positive. They're meta-instructions about how to manage context itself, not task-level prescriptions.

### The complete feedback loop

![Skills as Portable Instruction Set](https://raw.githubusercontent.com/Ladas/blog-content/main/research-context-engineering/diagrams/portable-skills.png)

No paper studies a system that combines all three: on-demand skills + subagent isolation + retrospective evolution. Each is studied independently. Kagenti integrates them:

1. **Skills** reduce upfront context cost (Paper 4)
2. **Subagents** prevent context rot during execution (Context Folding / Manus pattern)
3. **Retrospective** evolves skills based on experience (Papers 5, 6, 7, 8, 10)
4. **CI** enforces correctness without context cost (gap in literature)
5. **Worktrees** provide isolation for skill experiments (gap in literature)

## Open Questions

### 1. Skill library scaling (phase transition)

Paper 4 identifies a phase transition where selection accuracy degrades beyond a critical library size. At 85+ skills, is Kagenti approaching this threshold?

**Mitigation strategies from the literature:**
- Smart routers (parent skills auto-selecting sub-skills) reduce the effective selection space
- Progressive disclosure Level 1 metadata keeps per-skill discovery cost at ~20-50 tokens
- Tool Search Tool (Paper 4) achieves 85% overhead reduction for large libraries

**What to monitor:** Track skill invocation accuracy — how often does the agent select the right skill on first attempt?

### 2. The missing benchmark

No paper tests "minimal index + on-demand skills" vs "verbose AGENTS.md" on the same tasks. Kagenti's session analytics could provide data for this comparison by measuring success rates and costs across sessions.

### 3. Context Budget enforcement via hooks

Could the Context Budget rules (currently prescriptive text in CLAUDE.md) be enforced via Claude Code hooks instead? This would further reduce CLAUDE.md's prescriptive content. The `context-safe.sh` library is a step in this direction but is opt-in rather than enforced.

### 4. Automated skill evolution (MCE-style)

Paper 6's automated evolution achieves 16.9% mean improvement. Currently Kagenti's retrospective is human-in-the-loop. Could the retrospective skill:
- Automatically generate skill variants in worktrees?
- Run validation tasks against variants?
- Measure outcomes via session analytics?
- Retain the better variant?

This would close the gap between Kagenti's manual retrospective and MCE's automated evolution.

### 5. Experience bullets (ACE-style)

Paper 5's "bullets" — small reusable strategies accumulated from sessions — could enhance skills. Example: a `k8s:pods` skill that accumulates bullets like "CrashLoopBackOff with OOMKilled usually means memory limit too low" from actual debugging sessions. The retrospective already identifies these patterns; the gap is in persisting them within skills.

### 6. Cross-agent portability

AGENTS.md is becoming a cross-tool standard (Codex, Copilot, Cursor all support it). Skills are Claude Code-specific. Paper 4 notes this as an open challenge. However, the skill format (YAML frontmatter + Markdown) is agent-agnostic in structure — only the invocation mechanism is platform-specific.

### 7. Procedural memory migration (Mem^p)

Paper 10 shows procedural memory built from a stronger model retains value when migrated to weaker models. This suggests skills developed with Opus could remain effective when used with Sonnet or Haiku subagents — which is already how Kagenti operates (main agent on Opus, subagents on Haiku).

### 8. Knowledge-to-code ratio as health metric

Paper 12 tracks their context infrastructure at 24.2% of codebase size. What's Kagenti's ratio? If skills + CLAUDE.md + docs total N lines against the codebase size, is that ratio healthy? Paper 12 suggests this is domain-dependent (real-time distributed systems need more), but tracking it over time could signal when skills need expansion or pruning.

### 9. Context usage drop measurement

Paper 13's "usage drop" metric (18-43% of retrieved context unused during reasoning) could be measured for skills. Do agents actually use the skill content they load? Session analytics could track: when a skill is invoked, does the agent reference its instructions in subsequent actions? High usage drop on a skill suggests it's too verbose or misrouted.

### 10. Emergence-driven skill creation

Paper 12's heuristic — "if debugging consumed an extended session without resolution, create a specialist and restart" — could be formalized in the retrospective workflow. When `skills:retrospective` identifies a session with extended debugging in a specific domain, it could propose creating a new skill for that domain with the specific failure modes and solutions discovered.

### 11. Stale skill detection

Paper 12 built a Python drift detector that parses recent Git commits against spec-to-file mappings. Kagenti's `skills:scan` does gap analysis, but doesn't specifically detect stale skills — skills whose referenced files, commands, or patterns have changed since the skill was last updated. This could be automated: compare skill content (referenced paths, commands, configs) against recent diffs.

### 12. Scheduled maintenance cadence

Paper 12 reports ~5 min/session + 30-45 min biweekly review. Kagenti's retrospective is ad-hoc. A scheduled cadence (e.g., run `skills:retrospective` every 2 weeks, `skills:scan` monthly) could prevent skill drift from accumulating. Session analytics could trigger this automatically when cost trends or failure rates cross thresholds.

## New Research (Feb 2026 additions)

### "Agent Drift: Quantifying Behavioral Degradation" (Jan 2026)

- **ArXiv**: [2601.04170](https://arxiv.org/abs/2601.04170)
- **Key metric**: Agent Stability Index (ASI) — composite across 12 dimensions in 4 categories: response consistency (30%), tool usage patterns (25%), inter-agent coordination (25%), behavioral boundaries (20%)
- **Critical numbers**:
  - Detectable drift after median 73 interactions (IQR: 52-114)
  - Drift acceleration: 0.08 ASI points/50 interactions early → 0.19 points/50 interactions after 300
  - Task success rate: 87.3% → 50.6% with unchecked drift (-42%)
  - Human interventions: 0.31/task → 0.98/task (+216%)
  - Token usage: 12,400 → 18,900 (+52.4%)
- **Three mitigations**:
  - Episodic Memory Consolidation (prune stale context every 50 turns): 51.9% drift reduction
  - Drift-Aware Routing (prefer stable agents, reset drifting ones): 63.0% reduction
  - Adaptive Behavioral Anchoring (few-shot exemplars from baseline): 70.4% reduction
  - Combined: 81.5% drift reduction, 94.7% ASI retention (23% compute overhead)
- **Key finding**: Systems with explicit long-term memory (structured logs, vector DBs) showed 21% higher ASI retention vs conversation-history-only. External memory provides behavioral anchors resistant to drift.
- **Architectural rec**: Two-level hierarchies (router + specialists) significantly outperform both flat and deep (3+) architectures. This validates Kagenti's pattern: parent skills (routers) + sub-skills (specialists).
- **Testing insight**: Pre-deployment testing over <50 interactions captures only ~25% of eventual drift cases. Extended stress testing simulating hundreds of interactions is required.

### ICLR 2026 Workshop on Recursive Self-Improvement (Apr 2026)

- **Source**: [recursive-workshop.github.io](https://recursive-workshop.github.io/)
- **Status**: First workshop dedicated exclusively to RSI, ICLR 2026 in Rio de Janeiro
- **Relevance**: Formalizes the field around agents that diagnose failures, critique behavior, update representations, and modify tools — exactly the retrospective loop.

### Agent-Native Procedural Knowledge (SKILL.md Spec)

- **Source**: [sterlites.com](https://sterlites.com/blog/agent-native-procedural-knowledge-systems)
- **Key concept**: "Institutional memory" files (bugs.md, decisions.md, key_facts.md) as persistent guardrails preventing agents from repeating past mistakes
- **Progressive disclosure formula**: Same three-level architecture (metadata → body → resources)
- **Vision**: "Specification-Driven Development" with layered files: PROMPT.md (identity) → RULES.md (constraints) → SKILL.md (capabilities) → SPEC.md (objectives)

### Anthropic 2026 Agentic Coding Trends Report

- **Source**: [resources.anthropic.com](https://resources.anthropic.com/hubfs/2026%20Agentic%20Coding%20Trends%20Report.pdf)
- **Key claim**: 2026 is the year when agents reconfigure the software development lifecycle
- **Skills note**: "MCP provides secure connectivity to external software and data, while skills provide the procedural knowledge for using those tools effectively"

### Practical findings on skill maintenance

- **Skill burning**: Skills that linger in `.claude/skills/` but add nothing to current tasks compete for context window space ([dasroot.net](https://dasroot.net/posts/2026/02/ai-agent-tooling-claude-skills/))
- **Context-drift detector**: Paper 12's approach — parse recent Git commits against skill-to-file mappings, inject warnings when source changes without skill updates
- **Filesystem-based memory**: The "Manus" pattern — offloading memory to persistent markdown files (task_plan.md, findings.md, progress.md) to solve context window limits
- **Regression testing for skills**: Creating 50-200 focused prompts with expected signals, running nightly, tracking pass rates ([LLMOps approaches](https://onereach.ai/blog/llmops-for-ai-agents-in-production/))

## Proposed Features and Optimizations

Based on the full research synthesis (14 papers + latest findings), here are concrete features Kagenti could implement, organized by impact and feasibility.

### Feature 1: Skill Drift Detection (`skills:drift`)

**Problem**: Paper 12's primary failure mode — "agents trust documentation absolutely; out-of-date specs cause silent failures." Agent Drift paper shows degradation accelerates after ~300 interactions.

**Implementation**: A new skill or enhancement to `skills:scan` that:
1. Parses each skill's referenced file paths, commands, Helm values, k8s resources
2. Compares against `git diff main..HEAD` or recent commits
3. Flags skills whose referenced artifacts have changed since the skill was last modified
4. Generates a staleness score per skill

**Data sources**:
- Skill file: extract referenced paths (e.g., `charts/kagenti/values.yaml`), commands, config keys
- Git log: find commits touching those paths since skill's last commit
- Output: staleness report with specific drift points

**Trigger**: Run as part of `skills:retrospective` or on a scheduled cadence (biweekly, matching Paper 12's recommendation).

**Effort**: Low — mostly Grep + Git operations in a skill file.

### Feature 2: Session Experience Extraction (`skills:learn`)

**Problem**: Papers 5-8 all show that skills/context that evolve from experience outperform static versions (10.6-53.8% improvement). Currently Kagenti's retrospective identifies skill gaps manually.

**Implementation**: A skill that:
1. Scans recent session analytics (from `session:extract`)
2. Identifies recurring patterns: repeated debugging in a domain, frequently searched terms, common failure modes
3. Extracts "experience bullets" (Paper 5's term) — compact, reusable strategies
4. Proposes additions to existing skills OR creation of new skills

**Example output**:
```markdown
## Proposed additions to k8s:pods skill:

### New failure mode bullet:
- CrashLoopBackOff + OOMKilled → check memory limits in values.yaml
  (seen in 3 sessions over past 2 weeks, average 12 min debugging each)

### New failure mode bullet:
- ImagePullBackOff + "unauthorized" → check imagePullSecrets in namespace
  (seen in 2 sessions, resolved by creating docker-registry secret)
```

**Maps to**: Paper 6 (MCE agentic crossover), Paper 7 (CER experience replay), Paper 10 (Mem^p procedural memory)

**Effort**: Medium — requires session log analysis + skill file editing.

### Feature 3: Context Budget Enforcement via Hooks

**Problem**: CLAUDE.md Context Budget rules (1-3) are prescriptive text — the kind Paper 3 says hurts performance. Currently opt-in via `context-safe.sh`.

**Implementation**: Claude Code hooks that:
1. Intercept Bash tool calls
2. Check if command output would exceed ~5 lines (heuristic based on command type)
3. Automatically redirect to `/tmp/kagenti/` and return only exit code
4. No context file prescription needed — enforcement is invisible

**Commands to auto-redirect** (known verbose):
- `kubectl get/describe/logs` (except single-resource get)
- `helm template/install/upgrade`
- `pytest/uv run pytest`
- `gh run view --log-failed`
- `oc start-build --follow`

**Impact**: Removes Context Budget section from CLAUDE.md (saves ~50 lines of always-loaded context), replaces prescriptive rules with automatic enforcement. Paper 3 says this is strictly better — CI enforcement over context prescription.

**Effort**: Medium — requires hook development + testing.

### Feature 4: Skill Invocation Accuracy Tracking

**Problem**: Paper 4 warns of phase transition in skill selection accuracy at large library sizes. Kagenti has 85+ skills. No data on whether selection is accurate.

**Implementation**: Track in session analytics:
1. When a skill is invoked, was it the right one? (Heuristic: did the agent switch to a different skill within 3 turns?)
2. Skill invocation frequency distribution — which skills are used, which are dead weight?
3. Misrouting rate — how often does the agent invoke a parent router vs going directly to the right sub-skill?

**Metrics to track**:
- Invocation count per skill per week
- "Bounce rate" — skill invoked then abandoned within 2 turns
- Router effectiveness — parent skill correctly routing vs human correcting
- Never-invoked skills (candidates for pruning or merging)

**Maps to**: Paper 4 (phase transition), Agent Drift paper (tool usage patterns as 25% of ASI)

**Effort**: Low — add metadata to session analytics.

### Feature 5: Institutional Memory Files

**Problem**: Knowledge discovered during debugging sessions (failure modes, edge cases, domain-specific patterns) is lost between sessions unless manually codified into skills.

**Implementation**: Per-domain persistent files in `.claude/memory/`:
- `bugs.md` — resolved and recurring issues with root causes
- `decisions.md` — architectural decisions with rationale
- `patterns.md` — discovered patterns (e.g., "HyperShift cluster creation fails if VPC quota <5")

**How it works**:
1. Skills reference relevant memory files (e.g., `hypershift:cluster` reads `memory/hypershift-patterns.md`)
2. Retrospective skill appends new discoveries to memory files
3. Memory files are Level 3 context (cold memory — loaded on demand, not always)
4. `skills:learn` periodically promotes high-value memory entries into skill content

**Maps to**: Paper 12 (G4: "if you explained it twice, write it down"), Sterlites institutional memory pattern, Manus filesystem-based memory

**Effort**: Low — convention + skill updates.

### Feature 6: Emergence-Driven Skill Creation

**Problem**: New skills are created manually during retrospectives. Paper 12's heuristic — "if debugging consumed an extended session without resolution, create a specialist and restart" — could be automated.

**Implementation**: Enhancement to `skills:retrospective`:
1. Analyze session duration vs outcome by domain
2. Identify sessions where debugging in a specific area exceeded N minutes without resolution
3. Auto-generate a skill draft for that domain, populated with:
   - Failure modes encountered
   - Successful resolution steps
   - Referenced files and commands
4. Present draft for human review

**Trigger signals**:
- Session cost > 2x average for similar tasks
- >3 debugging tool calls in same file area without resolution
- Repeated Grep/Read cycles in same directory

**Maps to**: Paper 12 (G5: "When in doubt, create an agent and restart"), Paper 9 (self-evolving agents)

**Effort**: Medium — session analysis + skill template generation.

### Feature 7: Skill Health Dashboard

**Problem**: No centralized view of skill system health. Multiple signals exist (staleness, invocation rate, session costs) but aren't aggregated.

**Implementation**: Extension to `session:dashboard`:
1. **Staleness heatmap**: When was each skill last updated vs its referenced files?
2. **Usage distribution**: Which skills are heavily used, lightly used, never used?
3. **Cost attribution**: Which skills correlate with high/low session costs?
4. **Drift score**: Per-skill staleness score from Feature 1
5. **Evolution timeline**: How skills have changed over time (additions, updates, deletions)

**Visualization**: HTML dashboard (like existing `session:dashboard`) with skill-specific views

**Maps to**: Agent Drift paper (ASI monitoring), Paper 12 (knowledge-to-code ratio tracking)

**Effort**: Medium — extends existing analytics infrastructure.

### Feature 8: Two-Level Skill Routing Optimization

**Problem**: Agent Drift paper shows two-level hierarchies (router + specialists) significantly outperform flat and deep architectures. Kagenti has this with parent skills (tdd:, rca:, k8s:) routing to sub-skills, but not all skills have routers.

**Implementation**: Audit and optimize routing:
1. Identify skill clusters that lack a parent router
2. Create lightweight routers for under-served categories
3. Ensure router skills have minimal content (just routing logic, ~50 lines)
4. Track routing accuracy (Feature 4) to validate

**Current routers**: `tdd:`, `rca:`, `k8s:`, `test:`, `git:`, `auth:`, `session:`, `skills:`, `hypershift:`, `kagenti:`, `openshift:`

**Potential new routers**: `ci:` (partially exists), `helm:` (single skill, may not need router)

**Maps to**: Agent Drift paper (two-level hierarchy recommendation), Paper 4 (smart routers reduce effective selection space)

**Effort**: Low — audit + lightweight skill creation.

### Feature 9: Context Consolidation Check

**Problem**: ContextBench (Paper 13) shows 18-43% context usage drop — agents retrieve context but don't use it during reasoning. This may apply to skills too.

**Implementation**: Post-session analysis:
1. When a skill is loaded, track which sections of the skill the agent actually references in subsequent actions
2. Identify "dead sections" — skill content that is consistently loaded but never acted upon
3. Flag verbose skills where >40% of content is unused
4. Propose skill trimming during retrospective

**Example**: If `k8s:pods` loads 200 lines but agents only ever use the "CrashLoopBackOff" and "ImagePullBackOff" sections, the rest is context waste.

**Maps to**: Paper 13 (context usage drop), Paper 3 (verbose context hurts)

**Effort**: High — requires instrumentation of skill content usage within sessions.

### Feature 10: Adaptive Context Budget

**Problem**: Paper 6 (MCE) shows that optimal context length varies per task (1.5K tokens for simple, 86K for complex). Kagenti's context budget rules are one-size-fits-all.

**Implementation**: Adaptive rules based on task type:
1. **Simple tasks** (single file edit, config change): Minimal skills, aggressive output redirection
2. **Medium tasks** (feature implementation, debugging): Standard skill loading, subagent analysis
3. **Complex tasks** (multi-component refactoring, new subsystem): Relaxed limits, allow more context for planning

**How to detect task complexity**:
- Number of files expected to change
- Whether a plan was created
- Skill category (rca: = complex, git:commit = simple)

**Maps to**: Paper 6 (MCE learns per-task context length), Agent Drift paper (context window pollution as primary degradation mechanism)

**Effort**: High — requires task classification + dynamic rule adjustment.

### Feature 11: Compaction-Resilient Context (SessionStart Hook)

**Problem**: When Claude Code's context window fills, compaction summarizes the conversation — but critical details can be lost. Factory.ai's evaluation shows artifact tracking scores only 2.19-2.45/5.0 across all compression methods. Context Budget rules and skill state can be lost during compaction.

**Implementation**: A `SessionStart` hook with `compact` matcher that:
1. Re-injects critical context after every compaction event
2. Includes: current worktree, active cluster, LOG_DIR path, current task list state
3. Ensures Context Budget rules survive compaction without being in CLAUDE.md

**How it works** (Claude Code hooks support this natively):
```json
{
  "event": "SessionStart",
  "matcher": "compact",
  "type": "command",
  "command": "cat .claude/scripts/post-compaction-context.md"
}
```
The script outputs critical state to stdout, which Claude Code adds to context.

**Impact**: Moves more prescriptive content out of CLAUDE.md (always-loaded) into compaction-resilient hooks (loaded only when needed). Addresses Factory.ai's finding that structured section-based summaries prevent information drift.

**Maps to**: Factory.ai compression evaluation, Context Folding (FoldGRPO), Agent Drift mitigation (Episodic Memory Consolidation)

**Effort**: Low — single hook + markdown file.

### Feature 12: Skill Burning Prevention

**Problem**: At 85+ skills, Level 1 metadata (name + description) in the system prompt is non-trivial. Skills that are never used still consume discovery tokens. Industry reports note "install-heavy skills linger and compete for context window space."

**Implementation**:
1. Track skill invocation frequency (Feature 4)
2. After N sessions with zero invocations, flag skill as "cold"
3. Cold skills have metadata removed from system prompt (moved to a searchable index)
4. Agent can still discover cold skills via `skills:scan` or explicit search
5. Retrospective reviews cold skills for deprecation

**Three tiers of skill visibility**:
- **Hot**: Frequently used → metadata always in system prompt
- **Warm**: Occasionally used → metadata in system prompt
- **Cold**: Rarely/never used → discoverable but not in system prompt

**Maps to**: Paper 4 (phase transition at library scale), token optimization literature (40-80% savings from progressive disclosure), Agent Drift (tool usage patterns as stability metric)

**Effort**: Medium — requires invocation tracking + system prompt management.

### Feature 13: AGENTS.md Cross-Platform Export

**Problem**: AGENTS.md is now a Linux Foundation standard under AAIF (Agentic AI Foundation), adopted by 60,000+ repos, supported by Codex, Copilot, Cursor, Gemini CLI, and others. Kagenti's skills are Claude Code-specific. Cross-platform contributors can't benefit from the knowledge encoded in skills.

**Implementation**: A skill or script that:
1. Generates an AGENTS.md file from CLAUDE.md + skill metadata
2. Extracts key commands, conventions, and project structure from CLAUDE.md
3. Includes skill names and descriptions as a "capabilities" section
4. Keeps it minimal (Paper 3's recommendation: only minimal requirements)
5. Regenerated periodically (not manually maintained)

**AGENTS.md would contain**:
- Project overview (from CLAUDE.md)
- Build/test commands (from CLAUDE.md Key Commands table)
- Code style requirements (from CLAUDE.md)
- NOT: full skill content, verbose instructions, codebase overviews

**Maps to**: AAIF standardization, Paper 3 (minimal requirements only), Paper 1 (cross-tool context files)

**Effort**: Low — template + extraction script.

![Feature Priority Matrix](https://raw.githubusercontent.com/Ladas/blog-content/main/research-context-engineering/diagrams/feature-priority.png)

## Feature Priority Matrix

| Feature | Impact | Effort | Risk | Priority |
|---|---|---|---|---|
| 1. Skill Drift Detection | High — prevents silent failures | Low | Low | **P0** |
| 2. Session Experience Extraction | High — 10-53% improvement potential | Medium | Medium | **P1** |
| 3. Context Budget via Hooks | Medium — removes 50 lines from CLAUDE.md | Medium | Medium | **P1** |
| 4. Invocation Accuracy Tracking | Medium — early warning for phase transition | Low | Low | **P1** |
| 5. Institutional Memory Files | Medium — prevents knowledge loss | Low | Low | **P1** |
| 11. Compaction-Resilient Context | Medium — prevents info loss on compaction | Low | Low | **P1** |
| 6. Emergence-Driven Skill Creation | Medium — automates retrospective | Medium | Medium | **P2** |
| 7. Skill Health Dashboard | Medium — observability | Medium | Low | **P2** |
| 8. Two-Level Routing Optimization | Low — marginal improvement | Low | Low | **P2** |
| 12. Skill Burning Prevention | Medium — reduces discovery token cost | Medium | Medium | **P2** |
| 13. AGENTS.md Cross-Platform Export | Low — interoperability | Low | Low | **P2** |
| 9. Context Consolidation Check | High — addresses usage drop | High | Medium | **P3** |
| 10. Adaptive Context Budget | Medium — per-task optimization | High | High | **P3** |

## Research Gaps: What Nobody Has Studied Yet

Based on this synthesis, these are the studies that don't exist but should:

1. **Skills vs AGENTS.md A/B test**: No paper benchmarks "minimal index + on-demand skills" vs "verbose AGENTS.md" on the same tasks with the same agents. Kagenti's session data could be the first empirical evidence.

2. **CI enforcement vs context prescription**: No paper measures the cost/benefit of enforcing conventions via CI hooks vs prescribing them in context files. Paper 3 shows prescription costs 20% more tokens; nobody has measured what CI enforcement costs (likely near-zero context cost).

3. **Subagent context isolation at scale**: The Context Folding paper (FoldGRPO, [2510.11967](https://arxiv.org/abs/2510.11967)) demonstrates 90% context compression via learned branching into sub-trajectories. Kagenti does this manually via skills. Nobody has compared learned vs manual delegation strategies for coding agents.

4. **Skill evolution lifecycle**: Papers 5-8 show self-improving context works (10-53% improvement), but all use synthetic benchmarks. Nobody has studied skill evolution in a real production codebase over months — tracking which skills were added, updated, deprecated, and measuring the impact on session costs and success rates over time.

5. **Skill library scaling empirics**: Paper 4 predicts a phase transition. Paper 12 has 19 agents. Kagenti has 85+. At what library size does routing accuracy actually degrade for coding agents? No empirical data exists.

6. **Context compression + skills interaction**: Factory.ai shows compression loses artifact details (2.45/5.0 score). When a skill is loaded pre-compaction, does it survive? Does compaction-aware skill design (shorter, more structured) improve post-compaction continuity?

7. **Security of skill-based architectures**: Paper 14 documents agent vulnerabilities. Paper 4 shows 26.1% of community skills have vulnerabilities. Nobody has studied whether first-party skill architectures (like Kagenti's) are meaningfully safer than community marketplaces, or whether CI enforcement provides measurable security improvement over trust-based approaches.

## Industry Context (Feb 2026)

### AGENTS.md becomes a Linux Foundation standard

The Agentic AI Foundation (AAIF), formed December 2025, now stewards three foundational projects:
- **MCP** (Model Context Protocol) — from Anthropic
- **AGENTS.md** — from OpenAI
- **goose** — from Block

Platinum members: AWS, Anthropic, Block, Bloomberg, Cloudflare, Google, Microsoft, OpenAI. AGENTS.md adopted by 60,000+ repos. This standardization strengthens the case for Feature 13 (AGENTS.md export) but also validates the approach of keeping AGENTS.md minimal — the standard explicitly positions it as complement to README.md, not replacement.

### Claude Code hooks mature

As of February 2026, Claude Code hooks have 14 lifecycle events, 3 handler types (command, prompt, agent), and async execution. This makes Feature 3 (Context Budget via hooks) and Feature 11 (Compaction-Resilient Context) immediately implementable. The `compact` matcher on `SessionStart` is the specific mechanism for surviving compaction events.

### Token economics

Industry reports show 40-80% token waste is common due to poor serialization, redundant calls, and bloated contexts. Key strategies:
- Prompt caching: up to 90% on cached input tokens
- Smart context engine: 40-60% savings
- Intelligent model routing: 60-80% cost reduction
- Production compression targets: 3:1 to 5:1 for historical context, 10:1 to 20:1 for tool outputs

Kagenti's subagent pattern achieves effective compression ratios well within these targets (100-line log → 3-line summary = 33:1 ratio).

### Context Folding — theoretical foundation for subagents

The Context Folding paper ([2510.11967](https://arxiv.org/abs/2510.11967)) provides formal validation:
- Agent branches into sub-trajectory → processes subtask → folds results back as summary
- FoldGRPO achieves **90% context compression** (100K+ total tokens processed, 8K active context)
- +20% on BrowseComp-Plus, +8.8% on SWE-Bench Verified
- Validates Kagenti's manual subagent pattern as architecturally sound; FoldGRPO learns when to branch, while Kagenti prescribes it via skills

### ContextEvolve — multi-agent context compression

ContextEvolve ([2602.02597](https://arxiv.org/abs/2602.02597)) decomposes context into three orthogonal dimensions managed by specialized agents:
- **Semantic state** (what the code does) — Summarizer Agent
- **Optimization direction** (where to improve) — Navigator Agent
- **Experience distribution** (what worked before) — Sampler Agent

Results: 33.3% performance improvement, 29.0% token reduction. Key insight: "sampling should prioritize informative semantics, not only high scores" — include failed solutions with promising concepts. This maps to retrospective: extract learning from failures, not just successes.
