# Memory Systems Research: From Neuroscience to AI Agents to Kagenti

**Date**: 2026-02-27
**Type**: Research Synthesis
**Status**: Draft
**Related**: PR #758 (sandbox agent), Issue #708 (agent context isolation)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Part I: Brain Memory — Neuroscience Foundations](#2-part-i-brain-memory--neuroscience-foundations)
3. [Part II: Agent Memory Systems — Framework Landscape](#3-part-ii-agent-memory-systems--framework-landscape)
4. [Part III: Claude Code Memory — Architecture and Evolution](#4-part-iii-claude-code-memory--architecture-and-evolution)
5. [Part IV: Kagenti Sandbox Agent — Tying It All Together](#5-part-iv-kagenti-sandbox-agent--tying-it-all-together)
6. [Part V: Design Implications and Recommendations](#6-part-v-design-implications-and-recommendations)
7. [Sources](#7-sources)

---

## 1. Executive Summary

This research synthesizes three domains — cognitive neuroscience, AI agent memory frameworks, and Claude Code's memory management — to inform the memory architecture of Kagenti's sandbox agent (PR #758).

**Key findings:**

1. **Neuroscience has converged on a four-system memory taxonomy** (working, episodic, semantic, procedural) that has become the dominant framework for AI agent memory design. The brain's memory is not monolithic — it uses specialized, interacting subsystems with active consolidation and purposeful forgetting.

2. **The agent framework landscape is rapidly maturing.** LangGraph has replaced legacy memory with checkpointer + Store architecture. MemGPT/Letta treats context as virtual memory with OS-like tiering. Mem0 provides a standalone hybrid memory layer. Graph-based memory (Graphiti/Zep) is outperforming flat vector stores for temporal and multi-hop reasoning.

3. **Claude Code's memory has evolved from a single CLAUDE.md to a six-layer architecture** spanning managed policy, project memory, modular rules, user memory, auto-memory, and skills. Context budget management is the central engineering concern, with techniques like context editing (84% token reduction) and PreCompact hooks.

4. **Kagenti's sandbox agent already implements several memory patterns** (LangGraph MemorySaver/PostgresSaver, skills loading, session passover documents) but lacks structured long-term memory, cross-session consolidation, and multi-agent memory sharing — all areas where neuroscience and framework research point to clear solutions.

---

## 2. Part I: Brain Memory — Neuroscience Foundations

### 2.1 Human Memory Architecture

#### The Multi-Store Model (Atkinson & Shiffrin, 1968)

The foundational model proposes three sequential stores:
- **Sensory register** — raw input, sub-second duration
- **Short-term store** — limited capacity (~7 items), ~30 seconds
- **Long-term store** — unlimited capacity, indefinite duration

Information flows via attention, rehearsal, and encoding. This maps directly to AI agent memory tiers: raw input processing → context window (limited tokens) → external persistent storage.

> **Source**: Atkinson, R.C. & Shiffrin, R.M. (1968). "Human Memory: A Proposed System and Its Control Processes." *Psychology of Learning and Motivation*. [Wikipedia](https://en.wikipedia.org/wiki/Atkinson%E2%80%93Shiffrin_memory_model)

#### Baddeley's Working Memory Model (1974, updated 2000)

Refined short-term memory into a multi-component **working memory** system:

| Component | Function | AI Agent Analog |
|-----------|----------|-----------------|
| **Central executive** | Directs attention, coordinates | Planning/reasoning module |
| **Phonological loop** | Verbal/acoustic processing | Text processing buffer |
| **Visuospatial sketchpad** | Visual/spatial processing | Image/diagram processing |
| **Episodic buffer** (2000) | Integrates across modalities and time | Context integration layer |

The episodic buffer is particularly important: it suggests agents need a component that binds information across modalities and time into coherent "episodes" rather than treating all context as undifferentiated text.

> **Source**: Baddeley, A.D. & Hitch, G. (1974). *Psychology of Learning and Motivation*. See also: [Empowering Working Memory for LLM Agents (arXiv, 2023)](https://arxiv.org/pdf/2312.17259)

#### Long-Term Memory Taxonomy: Episodic, Semantic, Procedural

Long-term memory divides into neuroanatomically distinct but interacting systems:

```
Long-Term Memory
├── Explicit (Declarative)
│   ├── Episodic — personal experiences, time-bound (hippocampus)
│   │   "What happened when I tried approach X?"
│   └── Semantic — general facts, concepts (neocortex)
│       "What do I know about this API?"
└── Implicit (Non-Declarative)
    └── Procedural — skills, habits (cerebellum/basal ganglia)
        "How do I run the test suite?"
```

This taxonomy has become the dominant framework for AI agent memory design:
- **Episodic** → interaction logs, conversation histories, experience traces
- **Semantic** → knowledge bases, extracted facts, user preferences, vector databases
- **Procedural** → tool-use patterns, skills, prompt templates, fine-tuned weights

> **Sources**: Tulving (1972). See also: [From Human Memory to AI Memory (arXiv, 2025)](https://arxiv.org/html/2504.15965v1); [Frontiers in Cognition review (2025)](https://public-pages-files-2025.frontiersin.org/journals/cognition/articles/10.3389/fcogn.2024.1505549/pdf)

### 2.2 Memory Consolidation

#### Systems Consolidation: The Hippocampal-Neocortical Dialogue

Newly formed memories initially depend on the hippocampus, but over time (days to years) are gradually reorganized and transferred to neocortical networks. The Active Systems Consolidation model proposes this happens primarily during sleep.

**AI agent implication**: Raw conversation transcripts are like hippocampal traces — detailed but expensive to search. Consolidated summaries, extracted facts, and updated user models are like neocortical representations — more abstract but more efficient. **Effective memory requires an active consolidation process, not just accumulation.**

> **Sources**: [Sleep's contribution to memory formation (Physiological Reviews, 2025)](https://journals.physiology.org/doi/full/10.1152/physrev.00054.2024); [Systems memory consolidation during sleep (PMC, 2025)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12576410/)

#### Hippocampal Replay and Sharp-Wave Ripples

During sleep and quiet rest, the hippocampus replays compressed versions of recent experiences. Recent 2025 research shows that only a specific subset of **large sharp-wave ripples (SWRs)** drive memory reactivation, and their occurrence increases selectively after new learning.

**AI agent implication**: Agents should have "offline" processing periods for reviewing, compressing, and reorganizing recent experiences. Not all experiences are equally worth replaying — **selective replay based on novelty or importance** is more efficient than uniform processing.

> **Sources**: [Large SWRs promote memory reactivation (Neuron, 2025)](https://www.cell.com/neuron/abstract/S0896-6273(25)00756-1); [Awake replay (Trends in Neurosciences, 2025)](https://www.cell.com/trends/neurosciences/fulltext/S0166-2236(25)00037-2)

#### Memory Reconsolidation

When a consolidated memory is reactivated (retrieved), it enters a labile state and can be **updated, strengthened, or modified**. A 2025 study showed that sleep replay is especially critical for memory updating, not just initial consolidation.

**AI agent implication**: Agent memories should not be immutable. When encountering new information related to an existing memory, the existing memory should be retrievable, updatable, and re-stored with the new context. This is what systems like A-MEM implement.

> **Source**: [Long-Term Memory Updating (Advanced Science, 2025)](https://advanced.onlinelibrary.wiley.com/doi/10.1002/advs.202416480)

### 2.3 Memory Retrieval

#### Pattern Completion and Pattern Separation

The hippocampal CA3 performs **pattern completion**: given a partial cue, it reconstructs the full stored memory through recurrent attractor dynamics. The dentate gyrus performs **pattern separation**: making similar inputs maximally distinct to prevent interference.

**AI agent implication**: Pattern completion is the biological analog of similarity-based retrieval in vector databases. Pattern separation is the analog of ensuring stored memories have sufficiently distinct embeddings. **HippoRAG** (2024) explicitly implements both: knowledge graph triples for pattern separation, Personalized PageRank for pattern completion. It outperforms standard RAG by up to 20% on multi-hop QA.

> **Sources**: [Pattern Separation in Hippocampal CA3 (Science, 2008)](https://www.science.org/doi/10.1126/science.1152882); [HippoRAG (arXiv, 2024)](https://arxiv.org/abs/2405.14831)

#### Context-Dependent Retrieval

Memory recall is dramatically enhanced when the retrieval context matches the encoding context (Tulving's encoding specificity principle). The hippocampus binds contextual information to memory traces.

**AI agent implication**: Queries should include not just semantic content but contextual metadata — who was involved, when it happened, what task was active, what tools were in use. Simply doing semantic similarity search on content alone misses rich contextual cues. **Time-stamping, user-tagging, and task-tagging of memories become critical.**

#### Spreading Activation

Collins and Loftus (1975) proposed that concepts in semantic memory form a network where activation spreads from an accessed node to connected nodes. The strength of activation depends on association strength and network distance.

**AI agent implication**: This is the theoretical foundation for graph-based retrieval. HippoRAG's Personalized PageRank is a direct computational implementation. Graph-based retrieval outperforms flat vector search for multi-hop reasoning because the graph structure allows activation to spread across multiple associations.

> **Source**: [Collins & Loftus (1975)](https://www.researchgate.net/publication/200045115_A_Spreading_Activation_Theory_of_Semantic_Processing)

### 2.4 Forgetting Mechanisms

#### Interference Theory

Forgetting occurs primarily because similar memories interfere during retrieval, not simply through time-based decay:
- **Proactive interference**: old memories interfere with new ones
- **Retroactive interference**: new learning interferes with old memories

**AI agent implication**: The primary cause of "forgetting" in AI agents is not data loss but retrieval failure from interference by similar stored items. Solutions: pattern separation at encoding, metadata filtering, explicit disambiguation.

#### Retrieval-Induced Forgetting

Retrieving some memories actively suppresses related but non-retrieved memories through an inhibitory mechanism.

**AI agent implication**: Frequently retrieved memories become stronger while related but less relevant ones fade. This is both adaptive (natural pruning) and dangerous (valuable but infrequent memories may become inaccessible). Systems need both retrieval-based strengthening and periodic "review" of cold memories.

#### Active Forgetting

The brain has active forgetting mechanisms — intrinsic (molecular signaling to erode traces) and motivated (prefrontal inhibition of unwanted memories). **Forgetting is adaptive, not defective.**

**AI agent implication**: This is the most underappreciated insight. Current systems focus almost entirely on remembering. As Letta's team noted: "Agents can accumulate so much 'important' information that searching memory becomes slower than just processing the full context." Bio-inspired forgetting — time-based decay, usage-based pruning, interference-based displacement — is essential.

> **Sources**: [Biology of Forgetting (PMC, 2017)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5657245/); [Engram competition as forgetting (Trends in Neurosciences, 2025)](https://www.cell.com/trends/neurosciences/fulltext/S0166-2236(25)00153-5)

### 2.5 Key Neuroscience Theories Applied to AI

#### Complementary Learning Systems (CLS) Theory

The single most influential neuroscience theory for AI memory design (McClelland, McNaughton & O'Reilly, 1995; updated by Kumaran, Hassabis & McClelland, 2016):

| System | Brain Region | Learning Rate | Representations | AI Analog |
|--------|-------------|---------------|-----------------|-----------|
| **Fast learner** | Hippocampus | Rapid, one-shot | Sparse, non-overlapping | RAG database, conversation buffer |
| **Slow learner** | Neocortex | Gradual, interleaved | Distributed, overlapping | Fine-tuned model weights, knowledge base |

CLS directly explains:
- Why **experience replay** works in deep RL (simulates hippocampal replay)
- Why training one-at-a-time causes **catastrophic forgetting** (no interleaving)
- Why agents need both a fast-learning episodic store AND a slow-learning parametric store
- Why consolidation from episodic to semantic memory is necessary

> **Sources**: [McClelland, McNaughton & O'Reilly (1995)](https://stanford.edu/~jlmcc/papers/McCMcNaughtonOReilly95.pdf); [CLS Updated (Kumaran, Hassabis & McClelland, 2016)](https://www.cell.com/trends/cognitive-sciences/abstract/S1364-6613(16)30043-2)

#### Hippocampal Indexing Theory

The hippocampus does not store complete memories — it stores **indices (pointers)** to distributed traces across the neocortex. During retrieval, the index reactivates the original patterns, reconstructing the full memory.

**AI agent implication**: This is a direct conceptual analog to how RAG works — embeddings serve as indices pointing to full documents stored elsewhere. The key insight: **store lightweight indices (embeddings, knowledge graph nodes) that point to full content stored separately.**

> **Sources**: [Teyler & DiScenna (1986)](https://pubmed.ncbi.nlm.nih.gov/3008780/); [HippoRAG (arXiv, 2024)](https://arxiv.org/abs/2405.14831)

#### Predictive Coding and Salience Gating

Friston's predictive coding framework: the brain generates predictions and passes **prediction errors** upward. Dopamine serves as a **salience gate** determining which stimuli get prioritized for learning.

**AI agent implication**: Store what is surprising, compress what is expected. An agent's "dopamine analog" could be: task relevance scores, prediction error magnitude, user feedback signals, or explicit importance flags. Working memory (context window) should be protected from irrelevant information.

> **Sources**: [Friston (2009)](https://royalsocietypublishing.org/doi/abs/10.1098/rstb.2008.0300); [Dopamine encodes teaching signals (Cell, 2025)](https://www.cell.com/cell/fulltext/S0092-8674(25)00575-6)

### 2.6 Ten Principles from Neuroscience for AI Agent Memory

Drawing across all research surveyed:

1. **Multi-system architecture** — distinct but interacting systems for working, episodic, semantic, and procedural memory
2. **Active consolidation, not passive accumulation** — periodic offline processing to distill episodes into knowledge
3. **Selective encoding via salience gating** — not everything is worth remembering; gate by surprise, relevance, importance
4. **Reconstructive retrieval** — context-sensitive recall that may reconstruct rather than literally reproduce
5. **Functional forgetting** — active forgetting prevents overload and maintains retrieval efficiency
6. **Pattern separation AND completion** — make similar memories distinct AND reconstruct full memories from partial cues
7. **Prioritized replay** — selectively replay important/surprising experiences based on utility
8. **Stability-plasticity tradeoff** — protect confident knowledge from being overwritten by uncertain new information
9. **Memory as index, not storage** — lightweight pointers to distributed content, not monolithic stores
10. **Dual learning rates** — fast learning for episodes, slow learning for general knowledge; both necessary

---

## 3. Part II: Agent Memory Systems — Framework Landscape

### 3.1 The CoALA Taxonomy (Foundation)

The **Cognitive Architectures for Language Agents** paper (Sumers, Yao, Narasimhan & Griffiths, 2023) established the unified framework now referenced by nearly all agent memory work:

```
Agent Architecture
├── Information Storage
│   ├── Working Memory (short-term scratchpad)
│   └── Long-Term Memory
│       ├── Episodic (past events: "What happened when I tried X?")
│       ├── Semantic (factual knowledge: "API returns XML, not JSON")
│       └── Procedural (how to do tasks: code, prompts, tools)
├── Action Space
│   ├── Internal (reasoning, retrieval, learning)
│   └── External (tool use, communication)
└── Decision Making
    ├── Planning
    └── Execution
```

> **Source**: [CoALA (arXiv:2309.02427)](https://arxiv.org/abs/2309.02427)

### 3.2 LangChain / LangGraph Memory

#### Legacy (Deprecated in v0.3.1)

| Class | Approach | Weakness |
|-------|----------|----------|
| ConversationBufferMemory | Full history verbatim | Linear token cost growth |
| ConversationBufferWindowMemory | Last *k* messages | Loses old context |
| ConversationSummaryMemory | LLM summarizes history | Logarithmic growth, lossy |
| ConversationTokenBufferMemory | Token-budget truncation | Arbitrary cutoff |
| ConversationEntityMemory | Entity extraction | Narrow scope |

#### LangGraph's New Architecture

LangGraph replaces these with graph-based execution where memory is managed through **state**, **threads**, and **checkpoints**:

- **State** — structured object updated at each graph step (the "notebook page")
- **Threads** — isolated sessions by unique ID; enables multi-tenant applications
- **Checkpoints** — saved at every super-step; enables HITL, time travel, fault tolerance

**Checkpointer implementations:**

| Backend | Use Case | Persistence |
|---------|----------|-------------|
| `MemorySaver` | Prototyping | In-memory only |
| `SqliteSaver` | Local dev | File-based |
| `PostgresSaver` | Production | Database |
| `RedisSaver` | Production, distributed | Cache |
| `MongoDBStore` | Cross-thread persistence | Document DB |

#### Cross-Thread Memory (Long-Term)

While checkpointers provide thread-scoped (short-term) memory, cross-thread memory uses the **Store** interface for information that persists across different conversations:

- Memories saved as JSON documents organized by **namespace** (e.g., `("memories", user_id)`) and **key** (UUID)
- Namespace hierarchy enables flexible scoping: per-user, per-team, per-org, or global
- Can update "in the hot path" (during conversation) or on schedule (cron)

#### LangMem SDK (February 2025)

Dedicated library for long-term agent memory with three cognitive types:
- **Semantic Memory**: Facts that ground responses
- **Episodic Memory**: Past interactions stored as few-shot examples
- **Procedural Memory**: Learned procedures saved as updated system prompt instructions

Supports **prompt optimization** algorithms that generate proposals for updating the agent's system prompt based on accumulated procedural memory.

> **Sources**: [LangGraph Persistence Docs](https://docs.langchain.com/oss/python/langgraph/persistence); [LangMem SDK Launch](https://blog.langchain.com/langmem-sdk-launch/); [Memory for Agents (LangChain Blog, Dec 2024)](https://blog.langchain.com/memory-for-agents/)

### 3.3 MemGPT / Letta — Virtual Context Management

The paradigm shift: treat the LLM as an **operating system managing its own memory hierarchy**.

```
┌─────────────────────────────────┐
│ Core Memory (always in-context) │  ← CPU registers / L1 cache
│  - User info, agent persona     │
│  - Compressed essential facts    │
├─────────────────────────────────┤
│ Recall Memory (searchable)      │  ← RAM
│  - Semantic search over history  │
│  - Database-backed              │
├─────────────────────────────────┤
│ Archival Memory (long-term)     │  ← Disk
│  - Persistent important info    │
│  - Queryable when needed        │
└─────────────────────────────────┘
```

**Key innovations:**
- Agent manages its own context window through tool calls, deciding what to load/store/evict
- "Strategic forgetting" through summarization and targeted deletion
- **Memory blocks**: structured, editable blocks with character limits the agent can read and modify
- **Letta Code** (Dec 2025): Memory-first coding agent, #1 model-agnostic on Terminal-Bench
- **Context Repositories** (Feb 2026): Git-based versioning for programmatic context management

> **Sources**: [MemGPT (arXiv:2310.08560)](https://arxiv.org/abs/2310.08560); [Letta Docs](https://docs.letta.com/concepts/memgpt/); [Memory Blocks Blog](https://www.letta.com/blog/memory-blocks)

### 3.4 CrewAI Memory

CrewAI provides a structured, multi-type system for role-based agent crews:

**Traditional (four-type):**
- **Short-Term**: ChromaDB + RAG for current session
- **Long-Term**: SQLite3 for cross-session persistence
- **Entity Memory**: People, places, concepts via RAG
- **Contextual Memory**: Conversation coherence

**New unified Memory API:**
- Single `Memory` class with adaptive-depth recall
- Composite scoring: `recency_weight`, `semantic_weight`, `importance_weight`
- LLM analyzes content when saving (infers scope, categories, importance)

> **Source**: [CrewAI Memory Docs](https://docs.crewai.com/en/concepts/memory)

### 3.5 Google ADK

Google's Agent Development Kit provides structured memory through Sessions, State, and Memory services:

- **Sessions** — single interactions with events and temporary state
- **State** — key-value scratchpad with magic prefixes:
  - `user:` prefix → persists across all sessions for a specific user
  - `app:` prefix → persists across all sessions for all users
- **Memory** — searchable archive across conversations via `MemoryService`
- **Memory Tools**: `PreloadMemory` (automatic at turn start) and `LoadMemory` (on-demand)

> **Source**: [ADK Memory Docs](https://google.github.io/adk-docs/sessions/memory/); [Google Cloud Blog](https://cloud.google.com/blog/topics/developers-practitioners/remember-this-agent-state-and-memory-with-adk)

### 3.6 Mem0 — Universal Memory Layer

Framework-agnostic standalone memory layer combining vector, graph, and key-value stores:

- **Hybrid datastore**: key-value (structured facts) + graph (relationships) + vector (semantic similarity)
- **Mem0g** (graph-enhanced): stores memories as directed, labeled graphs with entity extraction
- **Performance**: 26% improvement over OpenAI baselines, 91% lower p95 latency, 90%+ token cost savings
- **"Memory Passport"** concept: your AI memory travels with you across apps and agents
- 41K+ GitHub stars, $24M raised from YC/Peak XV/Basis Set

> **Sources**: [Mem0 GitHub](https://github.com/mem0ai/mem0); [Mem0 Paper (arXiv, 2025)](https://arxiv.org/abs/2504.19413); [TechCrunch ($24M raise)](https://techcrunch.com/2025/10/28/mem0-raises-24m-from-yc-peak-xv-and-basis-set-to-build-the-memory-layer-for-ai-apps/)

### 3.7 OpenAI — Philosophical Shift

**Assistants API** (being deprecated, sunset August 2026):
- Server-side thread storage with automatic truncation
- Vector Stores for managed file search
- Re-processed entire thread per message → unpredictable costs

**Responses API** (successor):
- **Stateless by default**: application manages conversation state
- `previous_response_id` for simple chaining
- Shift from "OpenAI manages your state" to "you manage your state, we provide tools"

> **Sources**: [OpenAI Assistants Deprecation](https://www.eesel.ai/blog/openai-assistants-api); [Agents SDK Session Memory (OpenAI Cookbook)](https://cookbook.openai.com/examples/agents_sdk/session_memory)

### 3.8 Emerging Patterns

#### Graph-Based Memory is the New Frontier

**Graphiti** (by Zep AI) uses temporally-aware knowledge graphs with a **bi-temporal model** tracking both when events occurred and when they were ingested. Edges include validity intervals for conflict detection. Zep outperforms MemGPT on Deep Memory Retrieval benchmark (94.8% vs 93.4%).

Graph databases enable **multi-hop reasoning** that flat vector stores cannot do.

> **Sources**: [Graphiti (GitHub)](https://github.com/getzep/graphiti); [Zep Architecture (arXiv)](https://arxiv.org/html/2501.13956v1); [Graph-Based Agent Memory Survey (arXiv, Feb 2026)](https://arxiv.org/html/2602.05665)

#### Memory Compression Evolving to Agent-Specific

| Technique | Approach | Compression |
|-----------|----------|-------------|
| KVzip | KV cache compression | 3-4x |
| ACON | Agent-specific context optimization preserving action-outcome | 26-54% peak token reduction |
| Hierarchical Summarization | Progressive compression as info ages | Varies |
| Intelligent Memory Formation (Mem0) | Store only valuable facts | 80-90% token savings |

The field is evolving from generic text compression to **agent-specific compression** that preserves action-outcome relationships and decision cues.

> **Sources**: [KVzip (TechXplore, 2025)](https://techxplore.com/news/2025-11-ai-tech-compress-llm-chatbot.html); [ACON (OpenReview)](https://openreview.net/pdf?id=7JbSwX6bNL)

#### Multi-Agent Memory — Hardest Unsolved Problem

| Pattern | Description |
|---------|-------------|
| **Orchestrator-level** | Central coordinator as memory hub (blackboard) |
| **External hosting** | Shared database, no agent "owns" memory |
| **Collaborative Memory** (ICLR 2026) | Two-tier: private fragments + selectively shared fragments with provenance |

**Open challenges**: consistency models, memory protocols, cross-agent compression, coordinated forgetting.

> **Sources**: [Collaborative Memory (OpenReview, ICLR 2026)](https://openreview.net/forum?id=pJUQ5YA98Z); [Multi-Agent Memory (SIGARCH)](https://www.sigarch.org/multi-agent-memory-from-a-computer-architecture-perspective-visions-and-challenges-ahead/); [Memory Engineering (O'Reilly)](https://www.oreilly.com/radar/why-multi-agent-systems-need-memory-engineering/)

### 3.9 Key Academic Papers (2024-2026)

| Paper | Year | Key Contribution |
|-------|------|-----------------|
| [CoALA](https://arxiv.org/abs/2309.02427) | 2023 | Foundational taxonomy: working + LTM + actions + decisions |
| [Survey on Memory Mechanism](https://arxiv.org/abs/2404.13501) | 2024 | Comprehensive taxonomy grounded in cognitive psychology |
| [Memory in the Age of AI Agents](https://arxiv.org/abs/2512.13564) | 2025 | Memory lifecycle: formation → evolution → retrieval |
| [Graph-Based Memory Survey](https://arxiv.org/html/2602.05665) | 2026 | KG, temporal graphs, hypergraphs, hybrid approaches |
| [Reflexion](https://arxiv.org/abs/2303.11366) | 2023 | Verbal reinforcement learning via reflective episodic memory |
| [SAGE](https://arxiv.org/html/2409.00872v2) | 2024 | Self-evolving agents with Ebbinghaus forgetting curve integration |
| [MemAgents Workshop (ICLR 2026)](https://openreview.net/pdf?id=U51WxL382H) | 2026 | Dedicated workshop on memory for LLM-based agentic systems |

### 3.10 Framework Comparison Summary

| Dimension | LangGraph | Letta | CrewAI | Google ADK | Mem0 |
|-----------|-----------|-------|--------|------------|------|
| **Working memory** | State object | Core memory blocks | N/A | Session events | N/A |
| **Short-term** | Checkpointer (thread) | Recall memory (DB) | ChromaDB + RAG | Session state | N/A |
| **Long-term** | Store (cross-thread) | Archival memory | SQLite3 | MemoryService | Hybrid stores |
| **Episodic** | LangMem | Implicit in recall | Short-term memory | Session archive | Vector store |
| **Semantic** | LangMem | Core + archival | Entity memory | State + memory | Graph + vector |
| **Procedural** | LangMem prompt opt | Implicit in tools | N/A | N/A | N/A |
| **Graph support** | Via LangMem | No | No | No | Mem0g |
| **Multi-agent** | Shared Store | Conversations API | Crew-level sharing | Multi-agent sessions | Shared memory |

---

## 4. Part III: Claude Code Memory — Architecture and Evolution

### 4.1 Current Memory Architecture (Six Layers)

```
┌────────────────────────────────────────────────────────────┐
│ Layer 1: Managed Policy                                     │
│ /Library/Application Support/ClaudeCode/CLAUDE.md           │
│ Organization-wide IT/DevOps rules                           │
├────────────────────────────────────────────────────────────┤
│ Layer 2: Project Memory (shared via VCS)                    │
│ ./CLAUDE.md or ./.claude/CLAUDE.md                          │
│ Team conventions, build commands, architecture              │
├────────────────────────────────────────────────────────────┤
│ Layer 3: Modular Rules (shared via VCS)                     │
│ ./.claude/rules/*.md — path-specific, glob-matched          │
├────────────────────────────────────────────────────────────┤
│ Layer 4: User Memory (personal, all projects)               │
│ ~/.claude/CLAUDE.md — personal preferences                  │
├────────────────────────────────────────────────────────────┤
│ Layer 5: Local Project Memory (personal, gitignored)        │
│ ./CLAUDE.local.md — private project-specific prefs          │
├────────────────────────────────────────────────────────────┤
│ Layer 6: Auto-Memory (Claude-written, per project)          │
│ ~/.claude/projects/<project>/memory/                        │
│ MEMORY.md (first 200 lines loaded) + topic files            │
└────────────────────────────────────────────────────────────┘
```

**Additional memory mechanisms:**

| Mechanism | Type | Persistence | Purpose |
|-----------|------|-------------|---------|
| **Skills** (.claude/skills/) | Procedural | Git-tracked | Guided workflows, loaded on-demand |
| **Session Memory** | Episodic | Per-session file | Auto-extracted summaries (every ~5K tokens) |
| **Tasks** | Working | Disk-persisted | DAG-based, survive compaction |
| **Hooks** | Procedural | Git-tracked | Event-driven scripts (9 hook types) |
| **Subagents** | Working | Transcript files | Isolated context windows, resumable |

### 4.2 Evolution Timeline

```
Feb 2025 ─── CLAUDE.md only (single file, human-written)
                │
Jun-Sep 2025 ── Context Engineering era
                │ Memory Tool + Context Editing (API)
                │ 84% token reduction via context editing
                │ 39% perf improvement with memory tool
                │
Oct 2025 ────── Agent Skills introduced
                │ Three-level procedural memory
                │ Lazy-loading for context efficiency
                │
Dec 2025 ────── .claude/rules/ directory (modular rules)
                │ Background agents, named sessions
                │
Jan 2026 ────── Claude Code 2.0
                │ Tasks (DAG-based, survive compaction)
                │ PreCompact hooks (30% less info loss)
                │ Session forking, cloud handoff
                │
Feb 2026 ────── Auto-memory shipped
                │ Agent Teams (research preview)
                │ 1M context (Opus 4.6)
                │ Git worktree support
```

**Key trajectory:**
1. **Static → Dynamic**: CLAUDE.md (human-written) → auto-memory (Claude-written) → session memory (automatic)
2. **Monolithic → Modular**: Single file → rules/ with path-scoping → skills with lazy loading
3. **Single-session → Multi-session**: --continue/--resume → Tasks (persistent) → Agent Teams
4. **Passive → Active context management**: Simple loading → PreCompact hooks → context editing

### 4.3 Context Budget as First-Class Concern

Anthropic's consistent message: **intelligence is not the bottleneck — context is.**

| Technique | Impact | Mechanism |
|-----------|--------|-----------|
| Context editing | 84% token reduction | Auto-clear stale tool results |
| Memory tool | 39% performance gain | File-based external memory |
| PreCompact hooks | 30% less info loss | Custom export before compression |
| Plan mode | 53% token savings | Lighter model for reasoning |
| Skills lazy-loading | Minimal overhead | Load instructions only when needed |

**Auto-compaction**: Triggers at ~95% context usage. Passes history to model for summarization, preserving architectural decisions and unresolved bugs while discarding redundant outputs. Risk: "summarization of summarizations" causes progressive nuance loss (observed: 132K tokens → 2.3K, 98% reduction).

> **Sources**: [Effective Context Engineering (Anthropic)](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents); [Context Management (Claude API)](https://platform.claude.com/docs/en/build-with-claude/context-editing)

### 4.4 Comparison with Other Coding Agents

| Feature | Claude Code | Cursor | Aider | Devin |
|---------|-------------|--------|-------|-------|
| **Declarative memory** | CLAUDE.md hierarchy | .cursor/rules/ | .aider.conf | Knowledge entries |
| **Auto-memory** | MEMORY.md | Community hack | Repo map only | notes.txt + Wiki |
| **Context window** | 200K (1M beta) | 200K (70-120K effective) | Model-dependent | Model-dependent |
| **Compaction** | Auto at 95% | Auto (silent) | None (manual) | Unknown |
| **Multi-session** | Tasks, --resume, worktrees | Limited | Limited | Cloud-based |
| **Path-specific rules** | .claude/rules/ | .cursor/rules/ | .aiderignore | N/A |
| **Subagents** | fg/bg/resumable | Composer mode | No | Multi-Devin (2.0) |
| **Skills/procedural** | SKILL.md system | No | No | No |
| **Hooks** | 9 hook events | Limited | No | No |

**Notable approaches:**
- **Aider** uses a **repository map** built with tree-sitter + PageRank on file dependency graph — bottom-up, code-structure-aware (vs Claude Code's top-down CLAUDE.md approach)
- **Devin** uses agent-directed **notes.txt** + auto-generated **Wiki** — the agent decides what to note
- **Cursor** has rule types Claude Code lacks (Always, Auto Attached, Agent Requested) but rules "stick" less reliably (~33% ignore rate reported)

### 4.5 Mapping Claude Code to Neuroscience Memory Types

| Neuroscience Type | Claude Code Mechanism | Completeness |
|-------------------|----------------------|--------------|
| **Working memory** | Context window + Tasks | Strong (1M tokens, DAG tasks survive compaction) |
| **Episodic memory** | Session memory summaries | Partial (auto-extracted but limited cross-session retrieval) |
| **Semantic memory** | CLAUDE.md + auto-memory | Moderate (human-written facts + Claude's notes, but no structured KB) |
| **Procedural memory** | Skills (.claude/skills/) | Strong (three-level lazy-loading, domain-specific workflows) |
| **Consolidation** | /remember command | Weak (manual, user-initiated, session → CLAUDE.local.md only) |
| **Forgetting** | Auto-compaction | Crude (threshold-based compression, no salience-based pruning) |
| **Retrieval** | Grep/Glob/Read on memory files | Basic (text search, no semantic/vector retrieval) |

**Gaps identified:**
- No **semantic retrieval** over memories (just text matching)
- No **active consolidation** process (periodic distillation of episodes → knowledge)
- No **salience-based forgetting** (everything or nothing)
- No **cross-project memory** sharing
- No **graph-based** relational memory

---

## 5. Part IV: Kagenti Sandbox Agent — Tying It All Together

### 5.1 Current State (PR #758)

The sandbox agent (76 files, ~18K lines, draft PR) implements a comprehensive sandboxed coding agent with 18 capabilities across 9 phases:

**Memory-related capabilities already implemented:**

| Capability | Implementation | Memory Type |
|------------|---------------|-------------|
| **Conversation state** | LangGraph MemorySaver (thread_id = context_id) | Working memory |
| **Multi-pod persistence** | PostgresSaver (sandbox-legion, hardened, restricted variants) | Episodic memory |
| **Skills loading** | SkillsLoader (parses CLAUDE.md + .claude/skills/) | Procedural memory |
| **Workspace isolation** | WorkspaceManager (/workspace/ctx-{id}/) | Working memory isolation |
| **Configuration trust** | TOFU hash verification (SHA-256 in ConfigMap) | Semantic memory integrity |
| **Session passover** | Manual docs/plans/*.md documents | Institutional memory |

**Memory-related capabilities NOT yet implemented:**

| Priority | Feature | Gap |
|----------|---------|-----|
| **P0** | Multi-user message identity | No user context in memory |
| **P1** | Sub-agent child sessions | No hierarchical memory |
| **P2** | Automated session passover | Manual only; no consolidation |
| **P3** | HITL milestones | No approval state persistence |
| — | Long-term semantic memory | No extracted knowledge base |
| — | Cross-session memory search | No retrieval over past sessions |
| — | Memory consolidation | No episode → knowledge distillation |
| — | Memory forgetting/pruning | No active forgetting mechanism |

### 5.2 Agent Variants and Memory Trade-offs

| Variant | PostgreSQL | Security | Memory Characteristics |
|---------|-----------|----------|----------------------|
| **sandbox-legion** | Yes | Default | Full conversation persistence, vulnerable to memory theft |
| **sandbox-hardened** | Yes | Non-root, caps, seccomp | Persistent + secure, recommended for production |
| **sandbox-basic** | No | Hardened | Stateless — every session starts fresh |
| **sandbox-restricted** | Yes | Hardened + proxy | Most isolated, memory only accessible via restricted network |

### 5.3 How Neuroscience Principles Map to Kagenti

| Neuroscience Principle | Current Kagenti State | Opportunity |
|----------------------|----------------------|-------------|
| **Multi-system architecture** | Partial (checkpointer + skills) | Add semantic store (knowledge extracted from sessions) |
| **Active consolidation** | None (accumulate-only) | Background consolidation job: distill session logs → knowledge |
| **Salience gating** | None | Score memory entries by surprise/relevance; gate what enters LTM |
| **Context-dependent retrieval** | Basic (thread_id isolation) | Add metadata-rich retrieval (user, task type, tool, timestamp) |
| **Functional forgetting** | None | Time-decay, usage-based pruning, importance-weighted retention |
| **Pattern separation/completion** | None | Graph-based memory for multi-hop reasoning across sessions |
| **Prioritized replay** | None | Review surprising/failed interactions preferentially |
| **Stability-plasticity** | Implicit (PostgreSQL is append-only) | Reconsolidation: update existing memories when new info arrives |
| **Memory as index** | None | Embeddings → pointers to full session transcripts |
| **Dual learning rates** | Partial (fast checkpointer) | Add slow knowledge base that accumulates across sessions |

### 5.4 How Framework Patterns Map to Kagenti

| Framework Pattern | Kagenti Applicability | Implementation Path |
|-------------------|----------------------|---------------------|
| **LangGraph Store** (cross-thread) | Direct — already using LangGraph | Add `PostgresStore` for namespace-scoped long-term memory |
| **LangMem** (semantic/episodic/procedural) | High — natural extension | Wire LangMem's extractors into post-session processing |
| **Letta tiered memory** | Conceptual — inform architecture | Core memory (always in context) + recall (searchable DB) + archival (cold) |
| **Mem0 hybrid stores** | Possible standalone integration | Add as sidecar service for graph + vector memory |
| **CrewAI adaptive scoring** | Apply to memory retrieval | Composite scores: recency × semantic × importance |
| **Google ADK state prefixes** | Apply to memory scoping | `user:`, `team:`, `app:` prefixes for namespace isolation |
| **Graphiti temporal graphs** | Future — for multi-agent memory | Track when facts were learned and when they became invalid |

### 5.5 Proposed Memory Architecture for Kagenti Sandbox Agent

Based on neuroscience principles + framework landscape + current implementation state:

```
┌─────────────────────────────────────────────────────────────────┐
│ TIER 1: WORKING MEMORY (always in context)                       │
│                                                                   │
│ ┌─────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│ │ LLM Context     │  │ Task State       │  │ Active Skills   │  │
│ │ Window          │  │ (LangGraph State)│  │ (loaded on      │  │
│ │ (current conv)  │  │                  │  │  demand)        │  │
│ └─────────────────┘  └──────────────────┘  └─────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│ TIER 2: SESSION MEMORY (per-conversation, fast access)           │
│                                                                   │
│ ┌─────────────────────────────────────────────────────────────┐  │
│ │ PostgresSaver Checkpoints (thread_id = context_id)          │  │
│ │ Full conversation state, tool results, intermediate states  │  │
│ └─────────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│ TIER 3: LONG-TERM MEMORY (cross-session, searchable)  [NEW]     │
│                                                                   │
│ ┌───────────────┐  ┌────────────────┐  ┌──────────────────────┐ │
│ │ Semantic Store │  │ Episodic Store │  │ Procedural Store     │ │
│ │ (extracted     │  │ (session       │  │ (skills, learned     │ │
│ │  facts, user   │  │  summaries,    │  │  patterns, prompt    │ │
│ │  prefs, KB)    │  │  outcomes,     │  │  optimizations)      │ │
│ │               │  │  experiences)  │  │                      │ │
│ │ PostgresStore │  │ PostgresStore  │  │ .claude/skills/ +    │ │
│ │ + pgvector    │  │ + timestamps   │  │ PostgresStore        │ │
│ └───────────────┘  └────────────────┘  └──────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ TIER 4: CONSOLIDATION & FORGETTING ENGINE  [NEW]                 │
│                                                                   │
│ ┌────────────────────────┐  ┌──────────────────────────────────┐│
│ │ Consolidation Worker   │  │ Forgetting Worker               ││
│ │ - Post-session extract │  │ - Time-decay scoring            ││
│ │ - Episode → semantic   │  │ - Usage-based pruning           ││
│ │ - Conflict resolution  │  │ - Importance-weighted retention ││
│ │ - Summary generation   │  │ - Duplicate detection           ││
│ └────────────────────────┘  └──────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

**Key design decisions aligned with research:**

1. **Use LangGraph Store** (PostgresStore) for Tier 3 — already in the LangGraph ecosystem; namespace-scoped; supports cross-thread memory
2. **Post-session consolidation** — after each session ends, extract facts, outcomes, and patterns; consolidate into Tier 3 (mirrors hippocampal replay)
3. **Salience scoring at write time** — use LLM to assess surprise/importance of each memory entry before storage (mirrors dopamine gating)
4. **Composite retrieval scoring** — blend recency, semantic similarity, and importance weights (mirrors CrewAI's adaptive-depth recall)
5. **Time-decay forgetting** — reduce retrieval weight of unused memories over time (mirrors Ebbinghaus curve from SAGE paper)
6. **Namespace isolation** — `("user", user_id)`, `("team", team_id)`, `("agent", agent_id)` for memory scoping (mirrors Google ADK prefixes)
7. **Skills as procedural memory** — already implemented; extend with LangMem's prompt optimization for self-improving system prompts

### 5.6 Implementation Phases (Proposed)

| Phase | What | Neuroscience Analog | Framework Reference |
|-------|------|---------------------|---------------------|
| **Phase A** | Add PostgresStore for Tier 3 LTM alongside existing PostgresSaver | Add neocortex alongside hippocampus | LangGraph Store docs |
| **Phase B** | Post-session consolidation worker (extract facts/outcomes) | Hippocampal replay during sleep | LangMem extractors |
| **Phase C** | Semantic retrieval at session start (preload relevant memories) | Context-dependent retrieval | Google ADK PreloadMemory |
| **Phase D** | Salience scoring + importance-weighted storage | Dopamine gating | CrewAI importance_weight |
| **Phase E** | Time-decay forgetting + usage-based pruning | Active forgetting mechanisms | SAGE Ebbinghaus curve |
| **Phase F** | Cross-agent memory sharing with namespace isolation | Multi-agent memory protocols | Collaborative Memory (ICLR 2026) |
| **Phase G** | Graph-based relational memory (optional, future) | Spreading activation | Graphiti / Mem0g |

### 5.7 Connection to Existing Kagenti Research

This memory architecture connects to several existing research docs:

| Document | Connection |
|----------|------------|
| **2026-02-23-sandbox-agent-research.md** | C19 (multi-conversation isolation) needs memory isolation per namespace; C20 (sub-agent spawning) needs hierarchical memory |
| **2026-02-24-context-files-research-synthesis.md** | Paper 12's three-tier architecture (constitution/specialists/KB) maps directly to our Tier 1/Skills/Tier 3 |
| **2026-02-26-coding-agent-variants-research.md** | A2A wrapper pattern is memory-agnostic — any framework's memory can be exposed via A2A |
| **2026-02-18-sandbox-agent-passover.md** | The "Bob Beep" memory test validates MemorySaver works; now need to extend beyond single-session |
| **2026-02-27-sandbox-session-passover.md** | P2 (automated session passover) is exactly the consolidation worker from Phase B |

### 5.8 The Session Passover Problem as a Memory Problem

The most immediate practical problem is **P2: Automated Session Passover**. Currently, session continuity relies on manual docs/plans/*.md documents. This is exactly the memory consolidation problem:

**Current (manual hippocampal replay):**
```
Session ends → Human writes passover doc → Human reads it next session
```

**Proposed (automated consolidation):**
```
Session ends
  → Consolidation worker extracts:
      - Key decisions made (semantic memory)
      - What was tried and what happened (episodic memory)
      - Patterns learned (procedural memory)
      - Open questions and blockers (working memory for next session)
  → Stores in Tier 3 (PostgresStore)
  → Next session: agent queries Tier 3 for relevant context
  → Preloads into working memory (Tier 1)
```

This directly implements the brain's systems consolidation — hippocampal episodes (session transcripts) → neocortical knowledge (extracted facts and patterns).

---

## 6. Part V: Design Implications and Recommendations

### 6.1 Immediate Opportunities (Build on What Exists)

| # | Recommendation | Effort | Impact |
|---|---------------|--------|--------|
| 1 | **Add PostgresStore** alongside PostgresSaver for cross-session LTM | Low | High — enables all subsequent memory features |
| 2 | **Automated session passover** using LangMem-style extraction | Medium | High — solves P2, biggest manual pain point |
| 3 | **Preload relevant memories** at session start (like ADK's PreloadMemory) | Low | Medium — reduces context setup time |
| 4 | **Namespace-scoped memory** with user/team/agent isolation | Low | Medium — enables multi-tenant without memory leakage |

### 6.2 Medium-Term Enhancements

| # | Recommendation | Effort | Impact |
|---|---------------|--------|--------|
| 5 | **Salience scoring** at memory write time (LLM-based importance assessment) | Medium | Medium — reduces memory bloat |
| 6 | **Composite retrieval** scoring (recency × semantic × importance) | Medium | High — better memory recall |
| 7 | **Time-decay forgetting** with configurable half-life | Low | Medium — prevents unbounded memory growth |
| 8 | **Skills self-improvement** via LangMem procedural memory | High | High — agents that get better over time |

### 6.3 Future Research Directions

| # | Direction | Rationale |
|---|-----------|-----------|
| 9 | **Graph-based memory** (Graphiti/Mem0g integration) | Multi-hop reasoning, temporal tracking, relationship queries |
| 10 | **Cross-agent memory protocols** | Kagenti runs multiple agents; they should share learned knowledge |
| 11 | **Memory benchmarking** | Quantify memory quality, retrieval accuracy, consolidation loss |
| 12 | **Predictive memory preloading** | Use task context to predict which memories will be needed |

### 6.4 Anti-Patterns to Avoid

Based on research findings:

1. **Don't store everything** — "Agents can accumulate so much 'important' information that searching memory becomes slower than processing full context" (Letta). Active forgetting is essential.
2. **Don't use only vector search** — Graph-based retrieval outperforms for temporal and multi-hop reasoning. Hybrid stores (Mem0 pattern) are the production standard.
3. **Don't treat memories as immutable** — Reconsolidation (updating existing memories with new context) is critical. Append-only memory leads to bloat and contradiction.
4. **Don't over-engineer context files** — Paper 3 from our context-files research: LLM-generated context files actually reduced success by 0.5-2% while increasing cost 20-23%. Minimal, high-signal context wins.
5. **Don't ignore the consolidation step** — The gap between raw experience and useful knowledge requires active processing. Accumulation without consolidation is hoarding, not memory.

---

## 7. Sources

### Neuroscience

- Atkinson, R.C. & Shiffrin, R.M. (1968). "Human Memory." [Wikipedia](https://en.wikipedia.org/wiki/Atkinson%E2%80%93Shiffrin_memory_model)
- Baddeley, A.D. & Hitch, G. (1974). "Working Memory." [Simply Psychology](https://www.simplypsychology.org/multi-store.html)
- Tulving, E. (1972). "Episodic and Semantic Memory."
- Collins, A.M. & Loftus, E.F. (1975). [Spreading Activation Theory](https://www.researchgate.net/publication/200045115_A_Spreading_Activation_Theory_of_Semantic_Processing)
- McClelland, McNaughton & O'Reilly (1995). [CLS Theory](https://stanford.edu/~jlmcc/papers/McCMcNaughtonOReilly95.pdf)
- Kumaran, Hassabis & McClelland (2016). [CLS Updated](https://www.cell.com/trends/cognitive-sciences/abstract/S1364-6613(16)30043-2)
- Teyler & DiScenna (1986). [Hippocampal Indexing Theory](https://pubmed.ncbi.nlm.nih.gov/3008780/)
- Friston (2009). [Predictive Coding](https://royalsocietypublishing.org/doi/abs/10.1098/rstb.2008.0300)
- Kirkpatrick et al. (2017). [EWC / Catastrophic Forgetting](https://www.pnas.org/doi/10.1073/pnas.1611835114)
- Josselyn & Tonegawa (2020). [Memory Engrams](https://www.science.org/doi/10.1126/science.aaw4325)
- [From Human Memory to AI Memory (arXiv, 2025)](https://arxiv.org/html/2504.15965v1)
- [Sleep's Contribution to Memory (Physiological Reviews, 2025)](https://journals.physiology.org/doi/full/10.1152/physrev.00054.2024)
- [Large SWRs and Memory Reactivation (Neuron, 2025)](https://www.cell.com/neuron/abstract/S0896-6273(25)00756-1)
- [Awake Replay (Trends in Neurosciences, 2025)](https://www.cell.com/trends/neurosciences/fulltext/S0166-2236(25)00037-2)
- [Memory Updating (Advanced Science, 2025)](https://advanced.onlinelibrary.wiley.com/doi/10.1002/advs.202416480)
- [Biology of Forgetting (PMC, 2017)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5657245/)
- [Engram Stability (Neuropsychopharmacology, 2025)](https://www.nature.com/articles/s41386-024-01979-z)
- [Dopamine Teaching Signals (Cell, 2025)](https://www.cell.com/cell/fulltext/S0092-8674(25)00575-6)
- [Bayesian Continual Learning MESU (Nature Communications, 2025)](https://www.nature.com/articles/s41467-025-64601-w)
- [CLS for Continual Learning (arXiv, 2025)](https://arxiv.org/html/2507.11393)
- [HippoRAG (arXiv, 2024)](https://arxiv.org/abs/2405.14831)
- [The Emergence of NeuroAI (Nature Reviews Neuroscience, 2025)](https://www.nature.com/articles/s41583-025-00954-x)

### Agent Frameworks

- [CoALA (arXiv:2309.02427)](https://arxiv.org/abs/2309.02427)
- [Survey on Memory Mechanism (arXiv:2404.13501)](https://arxiv.org/abs/2404.13501)
- [Memory in the Age of AI Agents (arXiv:2512.13564)](https://arxiv.org/abs/2512.13564)
- [Graph-Based Agent Memory (arXiv, Feb 2026)](https://arxiv.org/html/2602.05665)
- [LangGraph Persistence Docs](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Memory Overview](https://docs.langchain.com/oss/python/langgraph/memory)
- [LangMem SDK Launch](https://blog.langchain.com/langmem-sdk-launch/)
- [LangMem GitHub](https://github.com/langchain-ai/langmem)
- [Memory for Agents (LangChain Blog)](https://blog.langchain.com/memory-for-agents/)
- [LangChain & LangGraph 1.0](https://blog.langchain.com/langchain-langgraph-1dot0/)
- [MemGPT Paper (arXiv:2310.08560)](https://arxiv.org/abs/2310.08560)
- [Letta Docs](https://docs.letta.com/concepts/memgpt/)
- [Letta Memory Blocks](https://www.letta.com/blog/memory-blocks)
- [CrewAI Memory Docs](https://docs.crewai.com/en/concepts/memory)
- [Google ADK Memory](https://google.github.io/adk-docs/sessions/memory/)
- [ADK State and Memory (Google Cloud)](https://cloud.google.com/blog/topics/developers-practitioners/remember-this-agent-state-and-memory-with-adk)
- [Mem0 GitHub](https://github.com/mem0ai/mem0)
- [Mem0 Paper (arXiv, 2025)](https://arxiv.org/abs/2504.19413)
- [Mem0 $24M Raise (TechCrunch)](https://techcrunch.com/2025/10/28/mem0-raises-24m-from-yc-peak-xv-and-basis-set-to-build-the-memory-layer-for-ai-apps/)
- [Graphiti GitHub](https://github.com/getzep/graphiti)
- [Zep Architecture (arXiv)](https://arxiv.org/html/2501.13956v1)
- [Reflexion (arXiv:2303.11366)](https://arxiv.org/abs/2303.11366)
- [SAGE (arXiv, 2024)](https://arxiv.org/html/2409.00872v2)
- [A-MEM (arXiv, 2025)](https://arxiv.org/pdf/2502.12110)
- [Collaborative Memory (OpenReview, ICLR 2026)](https://openreview.net/forum?id=pJUQ5YA98Z)
- [Multi-Agent Memory (SIGARCH)](https://www.sigarch.org/multi-agent-memory-from-a-computer-architecture-perspective-visions-and-challenges-ahead/)
- [Memory Engineering (O'Reilly)](https://www.oreilly.com/radar/why-multi-agent-systems-need-memory-engineering/)
- [MemAgents ICLR 2026 Workshop](https://openreview.net/pdf?id=U51WxL382H)
- [KVzip (TechXplore, 2025)](https://techxplore.com/news/2025-11-ai-tech-compress-llm-chatbot.html)
- [ACON (OpenReview)](https://openreview.net/pdf?id=7JbSwX6bNL)
- [OpenAI Assistants Deprecation](https://www.eesel.ai/blog/openai-assistants-api)
- [OpenAI Session Memory (Cookbook)](https://cookbook.openai.com/examples/agents_sdk/session_memory)
- [Memory-Augmented Transformers (arXiv, 2025)](https://arxiv.org/abs/2508.10824)
- [Titans (Google Research)](https://research.google/blog/titans-miras-helping-ai-have-long-term-memory/)

### Claude Code

- [Claude Code Memory Docs](https://code.claude.com/docs/en/memory)
- [Claude Code Skills Docs](https://code.claude.com/docs/en/skills)
- [Claude Code Sub-agents Docs](https://code.claude.com/docs/en/sub-agents)
- [Effective Context Engineering (Anthropic)](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Effective Harnesses for Long-Running Agents (Anthropic)](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Agent Skills (Anthropic Engineering)](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Context Editing (API Docs)](https://platform.claude.com/docs/en/build-with-claude/context-editing)
- [Context Management (Blog)](https://claude.com/blog/context-management)
- [Claude vs ChatGPT Memory (Simon Willison)](https://simonwillison.net/2025/Sep/12/claude-memory/)
- [Claude Code Session Memory (claudefast)](https://claudefa.st/blog/guide/mechanics/session-memory)
- [Claude Code Changelog](https://claudefa.st/blog/guide/changelog)
- [Claude Code CHANGELOG.md (GitHub)](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)
- [Understanding Claude Code Context Window (Galarza)](https://www.damiangalarza.com/posts/2025-12-08-understanding-claude-code-context-window/)
- [Skills Deep Dive (Lee Han Chung)](https://leehanchung.github.io/blogs/2025/10/26/claude-skills-deep-dive/)
- [How I Use Every Claude Code Feature (SSHH)](https://blog.sshh.io/p/how-i-use-every-claude-code-feature)
- [Writing a Good CLAUDE.md (HumanLayer)](https://www.humanlayer.dev/blog/writing-a-good-claude-md)

### Kagenti Internal

- [PR #758: Agent Sandbox (Draft)](https://github.com/kagenti/kagenti/pull/758)
- [Issue #708: Agent Context Isolation](https://github.com/kagenti/kagenti/issues/708)
- docs/plans/2026-02-23-sandbox-agent-research.md
- docs/plans/2026-02-24-sandbox-agent-implementation-passover.md
- docs/plans/2026-02-24-context-files-research-synthesis.md
- docs/plans/2026-02-25-sandbox-agent-passover.md
- docs/plans/2026-02-26-coding-agent-variants-research.md
- docs/plans/2026-02-27-sandbox-session-passover.md
