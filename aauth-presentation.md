# Agent Auth (AAuth) - Team Presentation

## Slides for Understanding AAuth Protocol

---

## Slide 1: Title
**Agent Auth (AAuth)**  
*Authentication and Authorization for AI Agents*

By Dick Hardt (OAuth 2.0 Author)  
IETF Draft - April 2026

---

## Slide 2: The Problem - Traditional OAuth Doesn't Work for Agents

### Traditional Software
- Knows what services it will call at **build time**
- Pre-registers with each service
- Gets `client_id` and `client_secret`
- Fixed integrations

### AI Agents Are Different
- Discover resources at **runtime**
- Don't know what they'll access ahead of time
- Execute long-running tasks across multiple services
- Need to explain **why** they're doing things
- Need authorization decisions **mid-task**

**Result:** OAuth 2.0's pre-registration model doesn't fit!

---

## Slide 3: Three Core Problems AAuth Solves

### Problem 1: No Independent Identity
- OAuth `client_id` at Google means nothing to GitHub
- Must register separately at each service
- Identity is "per-service", not portable

### Problem 2: Shared Secrets (API Keys)
- Bearer tokens = anyone with token can use it
- Secrets get copied, leaked, stolen
- No way to revoke without affecting all instances

### Problem 3: Cross-Domain Access
- SPIFFE works great **within** enterprise
- But doesn't help agents accessing external resources
- No way to operate across trust boundaries

---

## Slide 4: What AAuth Provides

### 🆔 Independent Identity
- Each agent: `aauth:weather-agent@kagenti.io`
- Works everywhere, no pre-registration

### 🔐 Cryptographic Proof-of-Possession
- Every request signed with agent's private key
- Stolen tokens are **useless** without the key
- No bearer tokens!

### 🌍 Runtime Discovery
- Agents discover resources as they go
- First API call **IS** the registration

### 📝 Natural Language Authorization (Missions)
- Agents explain what they're doing in plain language
- Users approve based on intent, not just scopes

---

## Slide 5: Key Concepts - Agent Identity

### Agent Identifier Format
```
aauth:local@domain

Examples:
  aauth:weather-agent@kagenti.io
  aauth:claude-instance-123@anthropic.com
  aauth:research-bot@company.com
```

### How It Works
- **Domain:** Globally unique (DNS)
- **Local:** Unique within that domain
- Like email addresses!

### Self-Published Identity
- Agent Server publishes metadata at `/.well-known/aauth-agent.json`
- No central registry
- Resources fetch keys via HTTPS

---

## Slide 6: The Three Servers

### 🏢 Agent Server
**Purpose:** Issues agent identity tokens  
**Trusts:** Agent instances (via K8s SA, certs)  
**Token issued:** Agent Token  
- Contains agent's identity
- Contains agent's public key
- Signed by Agent Server

### 👤 Person Server (PS)
**Purpose:** Represents the user/organization  
**Responsibilities:**
- Manage missions
- Handle user consent
- Issue authorization tokens
- Assert user identity

### 🚦 Access Server (AS)
**Purpose:** Policy enforcement for resources  
**Responsibilities:**
- Evaluate authorization policies
- Issue authorization tokens
- Enforce resource-specific rules
- Federation with Person Servers

---

## Slide 7: How Cryptographic Signatures Work

### Two Key Pairs Involved

#### 1. Agent Server's Keys
```
Private Key: Signs agent tokens (kept secret)
Public Key: Published at /.well-known/jwks.json
```

#### 2. Agent Instance's Keys
```
Private Key: Signs HTTP requests (stays in agent pod)
Public Key: Embedded in agent token
```

### The Magic: Two Signatures
1. **Agent Token signed by Agent Server** → Proves token is legitimate
2. **HTTP Request signed by Agent** → Proves agent has private key

**Attacker can't fake either!**

---

## Slide 8: Agent Token Structure

```json
{
  "iss": "https://kagenti.io",            ← Agent Server
  "sub": "aauth:weather-agent@kagenti.io", ← Agent identity
  "cnf": {                                 ← Confirmation claim
    "jwk": {                               ← Agent's PUBLIC key
      "kty": "EC",
      "crv": "P-256",
      "x": "...",
      "y": "...",
      "kid": "weather-instance-1"
    }
  },
  "ps": "https://ps.kagenti.io",          ← Person Server (optional)
  "iat": 1714435200,
  "exp": 1714521600,
  "jti": "unique-id-12345",
  "dwk": "aauth-agent.json"               ← Where to verify
}
```

**Signed with Agent Server's private key**

---

## Slide 9: HTTP Request with Signatures

```http
GET /repos/kagenti/kagenti/issues HTTP/1.1
Host: api.github.com

Signature-Input: sig1=("@method" "@path" "@authority");
    created=1714435200;keyid="weather-instance-1"

Signature: sig1=:MEUCIQDx7Y8zKm3jKQEWGw5jRdP8vL2hN...:

Signature-Key: sig1=jwt;jwt="eyJhbGciOiJFZERTQSIsInR5cCI6..."
```

### What's Happening
- **Signature-Input:** What was signed (method, path, authority)
- **Signature:** The actual signature bytes (signed with agent's private key)
- **Signature-Key:** The agent token (contains agent's public key)

### GitHub Verifies
1. Agent token signature (using Agent Server's key from `kagenti.io`)
2. Request signature (using agent's key from token)

---

## Slide 10: The Four Access Modes

AAuth supports **progressive adoption** through four modes:

| Mode | Parties | Complexity | Use Case |
|------|---------|------------|----------|
| **Identity-Based** | 2 | Simple | Agent + Resource decide |
| **Resource-Managed** | 2 | Medium | Resource handles auth |
| **PS-Managed** | 3 | Medium | User governance needed |
| **Federated** | 4 | Complex | Enterprise policies |

**Each mode builds on the previous**

---

## Slide 11: Mode 1 - Identity-Based Access

### Simplest: Resource Decides Based on Agent Identity

```
Agent → Resource: Signed request with agent token
Resource: "I see you're weather-agent@kagenti.io"
Resource: *Checks policy: Do I trust kagenti.io agents?*
Resource: "Yes" → Allow / "No" → Deny
```

### Flow
```
Agent                          Resource
  |                               |
  | HTTPSig w/ agent token        |
  |------------------------------>|
  |                               |
  | 200 OK (or 403)               |
  |<------------------------------|
```

### When to Use
- Internal tools
- Simple trust relationships
- Replace API keys with identity
- No user context needed

---

## Slide 12: Mode 2 - Resource-Managed Access (Two-Party)

### Resource Manages Authorization Itself

```
Agent → Resource: Request
Resource: "I need authorization"
Resource → Agent: "Go to this URL to authorize"
User: *Visits URL, approves, maybe pays*
Agent: *Polls for completion*
Resource → Agent: Access token
Agent → Resource: Request with access token
```

### Flow
```
Agent                          Resource
  |                               |
  | HTTPSig w/ agent token        |
  |------------------------------>|
  |                               |
  | 202 Accepted                  |
  | (interaction required)        |
  |<------------------------------|
  |                               |
  | [user completes interaction]  |
  |                               |
  | GET pending URL               |
  |------------------------------>|
  |                               |
  | 200 OK + access token         |
  |<------------------------------|
```

### When to Use
- First-call registration
- Payment required
- Account creation
- Resource has its own user database

---

## Slide 13: Mode 3 - PS-Managed Access (Three-Party)

### Person Server Represents the User

```
Agent → Resource: Request
Resource: "Get authorization from your Person Server"
Resource → Agent: Resource token (aud: PS)
Agent → Person Server: "I need access to GitHub"
Person Server → User: "Approve this?"
User: "Yes"
Person Server → Agent: Auth token (with user identity)
Agent → Resource: Request with auth token
Resource: "This is Alice via her PS" → Allow
```

### Flow
```
Agent                Resource              PS
  |                      |                 |
  | Request              |                 |
  |--------------------->|                 |
  |                      |                 |
  | Resource token       |                 |
  |<---------------------|                 |
  |                      |                 |
  | Request auth         |                 |
  |-------------------------------------->|
  |                      |                 |
  | Auth token           |                 |
  |<--------------------------------------|
  |                      |                 |
  | Access resource      |                 |
  |--------------------->|                 |
  |                      |                 |
  | 200 OK               |                 |
  |<---------------------|                 |
```

### When to Use
- Need user identity
- Governance/audit required
- Cross-organization access
- Mission-based authorization

---

## Slide 14: Mode 4 - Federated Access (Four-Party)

### Access Server Enforces Enterprise Policies

```
Agent → Resource: Request
Resource: "Get token from my Access Server"
Resource → Agent: Resource token (aud: AS)
Agent → PS: "I need access"
PS → AS: "Issue token for Alice's agent"
AS: *Checks policies, rate limits, time restrictions*
AS → PS: Auth token
PS → Agent: Auth token
Agent → Resource: Request with auth token
Resource: "Token from our AS" → Allow
```

### Flow
```
Agent              Resource    PS                AS
  |                   |        |                 |
  | Request           |        |                 |
  |------------------>|        |                 |
  |                   |        |                 |
  | Resource token    |        |                 |
  |<------------------|        |                 |
  |                   |        |                 |
  | Request token     |        |                 |
  |--------------------------->|                 |
  |                   |        |                 |
  |                   |        | Federation      |
  |                   |        |---------------->|
  |                   |        |                 |
  |                   |        | Auth token      |
  |                   |        |<----------------|
  |                   |        |                 |
  | Auth token        |        |                 |
  |<---------------------------|                 |
  |                   |        |                 |
  | Access            |        |                 |
  |------------------>|        |                 |
```

### When to Use
- Enterprise with many resources
- Complex policies (time, rate limits, compliance)
- Centralized audit
- GitHub, Google, AWS (large orgs)

---

## Slide 15: Missions - Natural Language Authorization

### What is a Mission?
A **scoped authorization context** that describes what an agent is trying to accomplish

### Mission Structure
```json
{
  "approver": "https://ps.kagenti.io",
  "agent": "aauth:weather-agent@kagenti.io",
  "approved_at": "2026-04-23T10:30:00Z",
  "description": "## Research Weather Integration\n\n
    Search kagenti/kagenti repository for weather-related 
    issues to understand user needs...",
  "approved_tools": [
    "github:search_issues",
    "github:read_issue"
  ],
  "constraints": {
    "duration": "24h",
    "max_api_calls": 100,
    "allowed_repos": ["kagenti/kagenti"]
  }
}
```

### Why Missions?
- **Intent-based:** Explain the "why", not just "what"
- **Human readable:** Natural language description
- **Audit trail:** Mission log tracks all actions
- **Adaptive:** Can clarify and adjust during execution

---

## Slide 16: Mission Lifecycle

```
1. PROPOSED
   Agent creates mission
   Submits to Person Server
   ↓

2. REVIEW & CLARIFICATION
   PS shows to user
   User asks questions
   Agent explains/adjusts
   ↓

3. APPROVED
   User approves
   PS signs mission
   Computes SHA-256 hash (s256)
   ↓

4. EXECUTION
   Agent makes requests
   PS includes mission in auth tokens
   Resources evaluate with context
   All actions logged to mission log
   ↓

5. COMPLETED/EXPIRED
   Mission reaches time limit
   Or agent declares complete
   PS archives mission log
```

---

## Slide 17: Mission vs Traditional Scopes

### Traditional OAuth Scope
```json
{
  "scope": "repo:read"
}
```
**Problem:**
- Too broad! Read ALL repos?
- For how long?
- For what purpose?
- No audit trail of intent

### Mission-Based Authorization
```json
{
  "scope": "repo:read",
  "mission": {
    "approver": "https://ps.kagenti.io",
    "s256": "abc123...",
    "description": "Research weather-related issues 
                   in kagenti/kagenti repo to 
                   understand user feature requests"
  }
}
```
**Benefits:**
- Specific intent
- Time-bounded
- Tool-limited
- Full audit trail
- Can detect anomalies

---

## Slide 18: Agent Token Acquisition Flow

```
┌──────────────────────────────────────────┐
│ 1. Agent Pod Starts                      │
│    - Generates key pair (EC P-256)       │
│    - Private key: Kept in memory         │
│    - Public key: Will share              │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ 2. Request Agent Token                   │
│                                          │
│    Agent → Agent Server:                 │
│    POST /token                           │
│    Authorization: K8s SA token           │
│    Body: {                               │
│      "agent_id": "weather-agent",        │
│      "public_key": { /* JWK */ }         │
│    }                                     │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ 3. Agent Server Validates                │
│    - Verify K8s service account          │
│    - Check pod authorization             │
│    - Create agent token with public key  │
│    - Sign with Agent Server's key        │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│ 4. Agent Receives Token                  │
│    - Stores agent token                  │
│    - Uses with private key for requests  │
└──────────────────────────────────────────┘
```

---

## Slide 19: Security Model - Why Attackers Can't Fake It

### Attack 1: Attacker Tries to Fake Agent Token
```
❌ Create fake token with own key
❌ Sign with attacker's private key
→ Resource fetches REAL kagenti.io keys via TLS
→ Signature verification FAILS
→ REJECTED
```

### Attack 2: Attacker Steals Agent Token
```
✓ Has the token
❌ Doesn't have agent's private key
❌ Can't sign requests
→ Request signature verification FAILS
→ REJECTED
```

### Attack 3: Attacker Uses Own Domain
```
✓ Can create valid tokens for evil.com
✓ Signatures verify
→ Resource checks: "Do I trust evil.com?"
→ NOT IN ALLOWLIST
→ REJECTED
```

### The Defense: Multiple Layers
1. **TLS/DNS** - Certificate authorities protect issuer authenticity
2. **Token Signature** - Agent Server vouches for agent
3. **Request Signature** - Proves agent has private key
4. **Domain Trust** - Resources choose which domains to trust

---

## Slide 20: Key Standards AAuth Builds On

| Standard | Year | What It Provides |
|----------|------|------------------|
| **JWT (RFC 7519)** | 2015 | Token format |
| **JOSE (RFC 7515-7518)** | 2015 | Signing & encryption |
| **RFC 7800 (`cnf` claim)** | 2016 | Proof-of-possession |
| **HTTP Message Signatures** | 2023 | Request signing (RFC 9421) |
| **Signature-Key** | 2026 | Key distribution (AAuth) |
| **AAuth Protocol** | 2026 | Complete workflow (IETF Draft) |

**AAuth is cutting edge, not widely adopted yet** (as of April 2026)

---

## Slide 21: The `cnf` (Confirmation) Claim

### What is `cnf`?
**RFC 7800** - Binds a token to a cryptographic key

### Problem Without `cnf`
```json
Bearer Token:
{
  "sub": "user123",
  "scope": "read"
}
```
**Anyone with this token can use it!** ✗

### Solution With `cnf`
```json
Proof-of-Possession Token:
{
  "sub": "user123",
  "scope": "read",
  "cnf": {
    "jwk": { /* public key */ }
  }
}
```
**Only holder of matching private key can use it!** ✓

### Not AAuth-Specific
Used in:
- OAuth 2.0 mTLS (RFC 8705)
- OAuth 2.0 DPoP (RFC 9449)
- WebAuthn
- AAuth

---

## Slide 22: Comparison with Existing Systems

### vs OAuth 2.0
| Aspect | OAuth 2.0 | AAuth |
|--------|-----------|-------|
| Identity | Per-service `client_id` | Global `aauth:id@domain` |
| Registration | Required at each service | None (self-published) |
| Tokens | Bearer (stealable) | Proof-of-possession |
| Discovery | Pre-configured | Runtime |
| Authorization | Scopes | Scopes + Missions |

### vs SPIFFE
| Aspect | SPIFFE | AAuth |
|--------|--------|-------|
| Scope | Single enterprise | Cross-organization |
| Identity | Workload ID | Agent ID |
| Trust | Single trust domain | Multiple domains |
| User context | No | Yes (via Person Server) |

### vs API Keys
| Aspect | API Keys | AAuth |
|--------|----------|-------|
| Type | Shared secret | Cryptographic identity |
| Theft protection | None | Proof-of-possession |
| Revocation | Affects all users | Per-instance |
| Audit | Limited | Rich (missions) |

---

## Slide 23: Kagenti Integration Scenarios

### Scenario 1: Kagenti Agents (Internal)
**Mode:** Identity-Based or PS-Managed  
```
Agent Server: kagenti.io
Agents: aauth:weather-agent@kagenti.io
         aauth:orchestrator@kagenti.io
```

### Scenario 2: External Agents (Claude, etc.)
**Mode:** PS-Managed or Federated  
```
Person Server: ps.kagenti.io (we control)
External agents:
  - aauth:claude-123@anthropic.com
  - aauth:custom@partner.com

PS vouches for these agents to access our resources
```

### Scenario 3: Multi-Agent Orchestration
**Mode:** PS-Managed with Missions  
```
Mission: "Deploy infrastructure to staging"
Agents involved:
  - aauth:orchestrator@kagenti.io (our agent)
  - aauth:claude@anthropic.com (planning)
  - aauth:builder@kagenti.io (execution)

All tracked under one mission
```

---

## Slide 24: Implementation Considerations

### What We Need

#### 1. Agent Server
- Issues agent tokens
- Authenticates agent instances (K8s SA)
- Publishes metadata at `/.well-known/aauth-agent.json`
- Can be integrated into Kagenti platform

#### 2. Person Server (Optional but Recommended)
- For mission-based governance
- User consent management
- Identity assertion
- Can integrate with existing Keycloak

#### 3. Agent Modifications
- Generate key pairs on startup
- Request agent tokens
- Sign HTTP requests (RFC 9421)
- Handle mission lifecycle

#### 4. Resource Support
- Verify signatures
- Implement trust policies
- Support AAuth challenge/response
- Optional: Mission-aware authorization

---

## Slide 25: Adoption Path for Kagenti

### Phase 1: Foundation (Months 1-2)
- Deploy Agent Server for kagenti.io domain
- Modify agents to use agent tokens
- Implement basic signature verification
- **Mode:** Identity-Based Access

### Phase 2: User Governance (Months 3-4)
- Deploy Person Server
- Implement mission creation/approval UI
- Add mission tracking
- **Mode:** PS-Managed Access

### Phase 3: Multi-Agent (Months 5-6)
- Support external agents (Claude, etc.)
- Implement clarification chat
- Mission log visualization
- **Mode:** PS-Managed with Missions

### Phase 4: Enterprise (Future)
- Access Server for complex policies
- Federation with external AS
- Advanced governance
- **Mode:** Federated Access

---

## Slide 26: Benefits for Kagenti

### Security
✓ No more API keys (proof-of-possession)  
✓ Per-instance identities  
✓ Stolen tokens are useless  
✓ Cryptographic verification  

### User Experience
✓ Agents explain what they're doing (missions)  
✓ Natural language authorization  
✓ Clarification chat during approval  
✓ Full audit trail  

### Operations
✓ No pre-registration (runtime discovery)  
✓ Works across trust domains  
✓ Scalable (no centralized registry)  
✓ Standards-based (IETF draft)  

### Multi-Agent Orchestration
✓ Track complex workflows  
✓ Govern external agents (Claude, GPT)  
✓ Mission-based coordination  
✓ Cross-organization access  

---

## Slide 27: Challenges & Considerations

### Adoption Challenges
- **New standard** (2026) - limited tooling/libraries
- **Complexity** - More complex than API keys
- **HTTP Message Signatures** - Not all clients support yet
- **Resource adoption** - Need resources to support AAuth

### Implementation Complexity
- **Key management** - Rotating, securing private keys
- **Mission UX** - Need good UI for mission approval
- **Federation** - PS↔AS integration complex
- **Backward compatibility** - Support existing auth during transition

### Operational Concerns
- **Debugging** - Signature failures can be opaque
- **Monitoring** - Need good observability
- **Certificate management** - TLS cert rotation
- **Performance** - Signature verification overhead

---

## Slide 28: Current State & Roadmap

### Implementations (April 2026)
- **TypeScript:** github.com/hellocoop/AAuth
- **Python:** github.com/christian-posta/aauth-full-demo
- **Java (Keycloak):** github.com/christian-posta/keycloak-aauth-extension
- **Rust (AgentGateway):** github.com/christian-posta/agentgateway

### Standards Status
- **HTTP Message Signatures:** RFC 9421 (2023) ✓
- **Signature-Key:** Internet Draft (2026)
- **AAuth Protocol:** Internet Draft (2026)

### Production Readiness
- 🟡 **Experimental** - Use for new projects, not production critical
- 🟡 **Library support** - Growing but limited
- 🟡 **Resource support** - Very few resources support yet
- 🟢 **Security model** - Sound, based on proven standards

---

## Slide 29: Comparison Chart - Which Mode to Use?

| Requirement | Identity-Based | Resource-Managed | PS-Managed | Federated |
|-------------|---------------|------------------|------------|-----------|
| User identity needed | ❌ | ✓ | ✓ | ✓ |
| Cross-org access | ✓ | ✓ | ✓ | ✓ |
| Mission governance | ❌ | ❌ | ✓ | ✓ |
| Enterprise policies | ❌ | ❌ | ❌ | ✓ |
| Setup complexity | Low | Low | Medium | High |
| Operational overhead | Low | Low | Medium | High |
| Audit trail | Basic | Basic | Rich | Rich |
| User consent | ❌ | ✓ | ✓ | ✓ |

**Recommendation for Kagenti:** Start with Identity-Based, evolve to PS-Managed

---

## Slide 30: Key Takeaways

### 🎯 Core Concepts
1. **Independent Identity** - Agents have portable, global identities
2. **Proof-of-Possession** - Tokens bound to keys, not bearer
3. **Runtime Discovery** - No pre-registration needed
4. **Four Modes** - Progressive adoption from simple to complex
5. **Missions** - Natural language authorization with audit

### 🔐 Security Model
- Two signatures: Token + Request
- Multi-layer verification
- TLS/DNS provides trust foundation
- Stolen tokens are useless

### 🚀 For Kagenti
- Enables secure multi-agent orchestration
- Governs external agents (Claude, GPT)
- Better than API keys
- Standards-based approach

### ⚠️ Considerations
- Cutting edge (2026) - early adopter risk
- Implementation complexity
- Need good tooling/UX

---

## Slide 31: Resources & Next Steps

### Learn More
- **Spec:** https://github.com/dickhardt/AAuth
- **Website:** https://www.aauth.dev
- **Demo:** https://blog.christianposta.com/aauth-full-demo/

### Implementations
- **Python Library:** https://github.com/christian-posta/aauth-implementation
- **Keycloak Extension:** https://github.com/christian-posta/keycloak-aauth-extension
- **AgentGateway:** https://github.com/agentgateway/agentgateway

### Next Steps for Kagenti
1. **Evaluate** - Assess fit for our multi-agent use cases
2. **Prototype** - Build Agent Server for kagenti.io
3. **Test** - Try with one agent + simple resource
4. **Decide** - PS-Managed vs Identity-Based for initial rollout
5. **Roadmap** - Phase adoption plan

### Questions?
Let's discuss how AAuth fits into Kagenti's architecture!

---

## Slide 32: Appendix - Example HTTP Exchange

### Complete Request/Response

**Request:**
```http
GET /repos/kagenti/kagenti/issues HTTP/1.1
Host: api.github.com
Content-Type: application/json

Signature-Input: sig1=("@method" "@path" "@authority");
    created=1714435200;keyid="weather-instance-1";alg="ecdsa-p256-sha256"

Signature: sig1=:MEUCIQDx7Y8zKm3jKQEWGw5jRdP8vL2hN+8xZ3r4tYqWpQ1sgQ
    IgK9fP3mH8dL2kN7vX9eR4tY6pZqW1sQ3jKm8yKdLx7Y=:

Signature-Key: sig1=jwt;jwt="eyJhbGciOiJFZERTQSIsInR5cCI6ImFhdGgt
    anNvbiJ9.eyJpc3MiOiJodHRwczovL2thZ2VudGkuaW8iLCJzdWIiOiJhYXV0aDp3
    ZWF0aGVyLWFnZW50QGthZ2VudGkuaW8iLCJjbmYiOnsiandrijoJa3R5IjoiRUMiL
    CJjcnYiOiJQLTI1NiIsIngiOiIuLi4iLCJ5IjoiLi4uIn19fQ.signature"
```

**Response (Success):**
```http
HTTP/1.1 200 OK
Content-Type: application/json

[
  {
    "number": 1242,
    "title": "Bug: DEFAULT_INTERNAL_REGISTRY hardcoded",
    ...
  }
]
```

**Response (Need Authorization):**
```http
HTTP/1.1 401 Unauthorized
AAuth-Requirement: requirement=resource_token;
    resource_token=eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9...

{
  "error": "authorization_required",
  "error_description": "Agent needs authorization to access this resource"
}
```

---

## Slide 33: Appendix - Key Terms Glossary

| Term | Definition |
|------|------------|
| **Agent Token** | JWT issued by Agent Server, contains agent identity and public key |
| **Auth Token** | JWT issued by PS or AS, grants access to resource |
| **Resource Token** | JWT issued by Resource, describes what access is needed |
| **cnf (Confirmation)** | JWT claim that binds token to a key (RFC 7800) |
| **HTTP Message Signature** | Signature of HTTP request components (RFC 9421) |
| **Mission** | Natural language description of agent's intent |
| **Mission Log** | Ordered record of all agent↔PS interactions |
| **Proof-of-Possession** | Token only usable by holder of private key |
| **Person Server (PS)** | Represents user, handles consent and governance |
| **Access Server (AS)** | Policy engine for enterprise authorization |
| **Agent Server** | Issues agent tokens, establishes agent identity |
| **JWK** | JSON Web Key - public key format |
| **JWKS** | JSON Web Key Set - collection of public keys |
| **dwk** | Dot well-known - metadata document name |

---

## End of Presentation

**Questions?**

