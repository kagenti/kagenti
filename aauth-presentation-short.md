---
marp: true
theme: default
paginate: true
---

# Agent Auth (AAuth)
## Authentication for AI Agents

**Dick Hardt** (OAuth 2.0 Author)  
IETF Draft - April 2026

Presented to Kagenti Team

---

# The Problem

## Traditional OAuth Doesn't Work for Agents

| Traditional Software | AI Agents |
|---------------------|-----------|
| Pre-registers with services | Discover at runtime |
| Fixed integrations | Dynamic resource access |
| Known permissions upfront | Need authorization mid-task |
| Uses `client_id` per service | Need portable identity |

**Bearer tokens (API keys)** = Anyone with token can use it ✗

**AAuth solution:** Cryptographic proof-of-possession ✓

---

# What is AAuth?

## Independent Agent Identity + Cryptographic Signatures

```
Agent Identity: aauth:weather-agent@kagenti.io
```

**Four Key Innovations:**

1. 🆔 **Portable Identity** - Works everywhere, no pre-registration
2. 🔐 **Proof-of-Possession** - Stolen tokens are useless
3. 🌍 **Runtime Discovery** - First API call IS the registration
4. 📝 **Missions** - Natural language authorization

**Built on:** HTTP Message Signatures (RFC 9421) + JWT

---

# How It Works: Two Signatures

## Agent Token (signed by Agent Server)

```json
{
  "iss": "https://kagenti.io",
  "sub": "aauth:weather-agent@kagenti.io",
  "cnf": {
    "jwk": { /* Agent's PUBLIC key */ }
  }
}
```
✅ Proves: Agent Server vouches for this agent

## HTTP Request (signed by Agent)

```http
Signature: sig1=:MEUCIQDx7Y8zKm3j...:
Signature-Key: jwt="eyJhbGci..." (contains agent token)
```
✅ Proves: Agent has the private key

**Attacker can't fake either signature!**

---

# The Three Servers

```
┌─────────────────┐
│ Agent Server    │  Issues agent identity tokens
│ kagenti.io      │  Contains agent's public key
└─────────────────┘

┌─────────────────┐
│ Person Server   │  Represents the user
│ ps.kagenti.io   │  Manages missions & consent
└─────────────────┘  Issues authorization tokens

┌─────────────────┐
│ Access Server   │  Enterprise policy engine
│ as.github.com   │  Enforces complex rules
└─────────────────┘  (optional, for large orgs)
```

---

# The Four Access Modes

| Mode | Parties | Flow | Use Case |
|------|---------|------|----------|
| **Identity-Based** | 2 | Agent → Resource | Simple, replace API keys |
| **Resource-Managed** | 2 | Agent ↔ Resource (user auth) | First-time registration |
| **PS-Managed** | 3 | Agent → PS → Resource | User governance needed |
| **Federated** | 4 | Agent → PS → AS → Resource | Enterprise policies |

**Start simple, add complexity as needed**

---

# Mode 1: Identity-Based (Simplest)

Resource decides based on agent identity

```
┌─────────┐                    ┌──────────┐
│  Agent  │  Signed request    │ Resource │
│         ├───────────────────>│          │
│         │                    │ "Trust   │
│         │  200 OK            │ kagenti? │
│         │<───────────────────┤ Yes ✓"   │
└─────────┘                    └──────────┘
```

**When to use:**
- Internal tools
- Simple trust relationships
- Replace API keys

**No user context, just agent identity**

---

# Mode 3: PS-Managed (Recommended)

Person Server represents the user

```
┌───────┐         ┌──────────┐         ┌────┐
│ Agent │────1───>│ Resource │         │ PS │
│       │  "Need  │          │         │    │
│       │  access"│          │         │    │
│       │         └──────────┘         └────┘
│       │<───2────  Resource token
│       │           (go to PS)
│       │
│       │────3────────────────────────>│    │
│       │    Request auth token        │    │
│       │                              │    │
│       │<───4─────────────────────────┤    │
│       │    Auth token (with user ID) │    │
│       │                              └────┘
│       │         ┌──────────┐
│       │────5───>│ Resource │
│       │  Access │  "Alice  │
│       │<────────┤  via PS" │
│       │  200 OK └──────────┘
└───────┘
```

**Provides:** User identity, missions, audit, governance

---

# Missions: Natural Language Authorization

## Traditional Scope
```json
{ "scope": "repo:read" }
```
❌ Too broad! Read ALL repos? For how long? Why?

## Mission
```json
{
  "description": "Research weather-related issues in 
                 kagenti/kagenti to understand user needs",
  "approved_tools": ["github:search_issues", "github:read_issue"],
  "constraints": {
    "duration": "24h",
    "max_api_calls": 100,
    "allowed_repos": ["kagenti/kagenti"]
  }
}
```
✅ Specific intent, time-bounded, auditable

**User approves based on "why", not just "what"**

---

# Security: Why Attackers Can't Fake It

## Attack 1: Fake Agent Token
```
❌ Attacker creates token with own key
❌ Signs with attacker's private key
→ Resource fetches REAL kagenti.io keys via TLS
→ Signature doesn't match
→ REJECTED ✓
```

## Attack 2: Steal Agent Token
```
✓ Attacker has token
❌ Doesn't have agent's private key
❌ Can't sign requests
→ Request signature fails
→ REJECTED ✓
```

**Multi-layer defense:** TLS/DNS + Token signature + Request signature

---

# Kagenti Integration Scenarios

## Scenario 1: Internal Agents
```
Agent Server: kagenti.io
Agents: aauth:weather-agent@kagenti.io
Mode: Identity-Based or PS-Managed
```

## Scenario 2: External Agents (Claude, GPT)
```
Person Server: ps.kagenti.io (we control)
Agents: aauth:claude-123@anthropic.com
        aauth:gpt-456@openai.com
Mode: PS-Managed (we govern them)
```

## Scenario 3: Multi-Agent Orchestration
```
Mission: "Deploy staging infrastructure"
Agents: orchestrator@kagenti.io (ours)
        claude@anthropic.com (planning)
        builder@kagenti.io (execution)
Mode: PS-Managed with Missions
```

---

# Adoption Path for Kagenti

## Phase 1: Foundation (2 months)
- Deploy Agent Server for kagenti.io
- Agents generate keys, request tokens
- Basic signature verification
- **Mode:** Identity-Based

## Phase 2: Governance (2 months)
- Deploy Person Server
- Mission creation/approval UI
- Mission tracking and logs
- **Mode:** PS-Managed

## Phase 3: Multi-Agent (Future)
- Support external agents (Claude, etc.)
- Clarification chat
- Advanced governance
- **Mode:** Federated (optional)

---

# Key Takeaways

## ✅ Benefits
- **Security:** Proof-of-possession, no stolen tokens
- **User Experience:** Natural language missions, audit trail
- **Operations:** No pre-registration, scalable
- **Multi-Agent:** Govern external agents, cross-org access

## ⚠️ Challenges
- **Cutting edge** (2026) - early adopter risk
- **Complexity** - More than API keys
- **Tooling** - Limited library support
- **Adoption** - Few resources support yet

## 🎯 Recommendation
Start with **PS-Managed mode** for Kagenti
- Enables governance and missions
- Works with external agents
- Provides audit trail
- Standards-based future

---

# Resources & Next Steps

## Learn More
- **Spec:** https://github.com/dickhardt/AAuth
- **Website:** https://www.aauth.dev
- **Demo:** https://blog.christianposta.com/aauth-full-demo/

## Implementations
- Python, Java (Keycloak), TypeScript, Rust

## Next Steps
1. ✅ **Understand** - This presentation
2. 🎯 **Evaluate** - Does it fit our multi-agent needs?
3. 🔬 **Prototype** - Build Agent Server for kagenti.io
4. 🧪 **Test** - One agent + simple resource
5. 🚀 **Decide** - Adoption plan and timeline

**Questions? Let's discuss!**

