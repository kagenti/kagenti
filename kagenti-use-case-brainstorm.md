# Kagenti Use Case Brainstorming
**Date:** 2026-05-19  
**Focus:** Identity, Access Control, Trust, and Platform Primitives

## Kagenti Feature Inventory

### Core Identity & Trust Features
- **SPIFFE/SPIRE** - Cryptographic workload identities with attestation
- **Keycloak** - OAuth2/OIDC identity provider with RBAC
- **AuthBridge** - Transparent JWT validation and token exchange (RFC 8693)
- **Dynamic Client Registration** - Operator-managed Keycloak client creation using SPIFFE IDs
- **Short-lived Tokens** - Audience-scoped tokens with automatic rotation
- **Zero-Trust Architecture** - No implicit trust, continuous verification

### Access Control & Security
- **Fine-grained RBAC** - Per-resource permissions (e.g., `slack-full-access` vs `slack-partial-access`)
- **Token Exchange** - Service-to-service auth with minimal privilege scopes
- **Istio Ambient Mesh** - Transparent mTLS without sidecars
- **Network Policies** - Kubernetes-native network segmentation
- **Audit Trails** - Request logging and observability

### Agent & Protocol Support
- **A2A Protocol** - Agent-to-agent communication with identity delegation
- **MCP Protocol** - Tool integration with authentication
- **Framework-Neutral** - LangGraph, CrewAI, AG2, AutoGen, etc.
- **Multi-agent Workflows** - Orchestrator → Worker patterns with identity propagation

### Observability & Operations
- **Phoenix** - LLM tracing and observability (optional)
- **MLflow** - Model tracking and experiment management (optional)
- **OpenTelemetry** - Distributed tracing with OTLP
- **Kiali** - Service mesh visualization

### Platform Features
- **Shipwright Builds** - Build agents/tools from source
- **Triggers/Eventing** - Event-driven agent activation (feature flag)
- **MCP Gateway** - Centralized tool discovery and routing
- **Multi-namespace Isolation** - Team-based segregation

---

## Use Case Proposals

### 1. **Academic Research Intelligence Platform** (Gosia's Suggestion - Enhanced)

**Overview:** Multi-agent system that discovers, evaluates, classifies, and curates high-quality academic papers with granular access controls and trust boundaries.

#### Agent Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     User (Researcher Role)                      │
│              Identity: user@university.edu                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │ JWT (aud: orchestrator)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Orchestrator Agent (team1/research-orchestrator)               │
│  - Receives user query                                          │
│  - Delegates to specialized agents via A2A                      │
│  - Aggregates results                                           │
│  SPIFFE: spiffe://kagenti.io/ns/team1/sa/research-orchestrator  │
└──────┬───────────┬────────────┬──────────────┬──────────────────┘
       │           │            │              │
       │ Token     │ Token      │ Token        │ Token
       │ Exchange  │ Exchange   │ Exchange     │ Exchange
       ▼           ▼            ▼              ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐
│ Crawler  │ │  Peer    │ │Classifier│ │    Query      │
│  Agent   │ │ Review   │ │  Agent   │ │    Agent      │
│          │ │  Agent   │ │          │ │               │
│ (team1)  │ │ (team2)  │ │ (team1)  │ │   (team1)     │
└────┬─────┘ └────┬─────┘ └────┬─────┘ └───────┬───────┘
     │            │            │                │
     ▼            ▼            ▼                ▼
┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
│Internet │ │Academic  │ │ML Model  │ │  Vector DB   │
│Crawler  │ │Database  │ │Service   │ │  (Read)      │
│Tool(MCP)│ │Tool(MCP) │ │Tool(MCP) │ │  Tool (MCP)  │
└─────────┘ └──────────┘ └──────────┘ └──────────────┘
                                            ▲
                                            │
                      ┌─────────────────────┘
                      │ Write access only
                      │
              ┌───────┴────────┐
              │  Indexer Agent │
              │    (team2)     │
              └────────────────┘
```

#### Identity & Access Control Flow

**Phase 1: Discovery (Crawler Agent)**
- **Identity:** `spiffe://kagenti.io/ns/team1/sa/paper-crawler`
- **Permissions:** 
  - Internet access (arxiv.org, pubmed.gov, IEEE Xplore) - READ only
  - S3 bucket (raw papers) - WRITE
  - No database access
- **Token Audience:** `internet-crawler-tool`, `s3-storage`
- **Access Control:** Network policies restrict outbound to approved academic domains only

**Phase 2: Peer Review (Evaluation Agent)**
- **Identity:** `spiffe://kagenti.io/ns/team2/sa/peer-reviewer`
- **Permissions:**
  - Academic database API - READ (citation graphs, h-index data)
  - LLM service - READ (for quality assessment)
  - S3 bucket (raw papers) - READ
  - S3 bucket (reviewed papers) - WRITE
  - No internet access
- **Token Audience:** `academic-db-tool`, `llm-service`, `s3-storage`
- **Token Exchange:** Receives delegated token from orchestrator with user context

**Phase 3: Classification (ML Agent)**
- **Identity:** `spiffe://kagenti.io/ns/team1/sa/paper-classifier`
- **Permissions:**
  - ML model service - READ
  - S3 bucket (reviewed papers) - READ
  - Vector DB - WRITE (embeddings)
  - No internet, no raw data access
- **Token Audience:** `ml-model-service`, `vector-db-tool`

**Phase 4: Indexing (Storage Agent)**
- **Identity:** `spiffe://kagenti.io/ns/team2/sa/indexer`
- **Permissions:**
  - Vector DB - WRITE (full access)
  - PostgreSQL - WRITE (metadata)
  - S3 bucket - READ (all processed papers)
- **Token Audience:** `vector-db-tool`, `postgres-db`

**Phase 5: Query (User-facing Agent)**
- **Identity:** `spiffe://kagenti.io/ns/team1/sa/research-query`
- **Permissions:**
  - Vector DB - READ only
  - PostgreSQL - READ only
  - No write access anywhere
- **Token Audience:** `vector-db-tool-read`, `postgres-db-read`
- **User Context:** Inherits user identity from JWT, enforces user-level RBAC

#### Kagenti Features Demonstrated

✅ **Identity:**
- SPIFFE workload identities for each agent
- JWT SVID attestation
- Dynamic Keycloak client registration

✅ **Access Control:**
- Fine-grained per-agent permissions
- Token exchange with audience scoping
- Read/Write separation
- Network policy enforcement
- User context propagation

✅ **Trust:**
- Zero-trust boundaries between phases
- No agent can access upstream or downstream resources
- Continuous token validation
- Short-lived credentials (60s)

✅ **Multi-Agent:**
- 5-agent collaboration via A2A protocol
- Identity delegation through orchestrator
- Cross-namespace communication (team1 ↔ team2)

✅ **Observability:**
- Phoenix traces for LLM calls in peer review
- MLflow for classification model metrics
- OpenTelemetry for end-to-end request tracing
- Kiali for service mesh visualization

✅ **Protocols:**
- A2A for agent-to-agent
- MCP for tool access (crawlers, databases, ML services)

✅ **Eventing (if enabled):**
- Trigger crawler on schedule (daily arXiv updates)
- Trigger review pipeline on new papers in S3
- Trigger reindexing on classification completion

#### User Roles & Permissions

| User Role | Keycloak Roles | Agent Access | Capabilities |
|-----------|----------------|--------------|--------------|
| **Senior Researcher** | `research-full-access` | All agents | Initiate crawls, review papers, query database |
| **Junior Researcher** | `research-read-access` | Query agent only | Search and read papers, no new crawls |
| **Librarian** | `research-curator` | Indexer agent | Manage classifications, curate collections |
| **Admin** | `research-admin` | All + audit | Full access + access logs and traces |

#### Demo Scenario

1. **User authenticates** as `senior-researcher@university.edu` via Keycloak
2. **User submits query** to orchestrator: "Find papers on Zero-Trust AI published in 2025-2026"
3. **Orchestrator delegates:**
   - Crawler agent: Search arXiv, IEEE for matching papers
   - Peer review agent: Evaluate citation quality, author reputation
   - Classifier agent: Extract topics, generate embeddings
   - Indexer agent: Store in vector DB
   - Query agent: Retrieve and rank results
4. **Each step shows:**
   - Token exchange logs (SPIFFE ID → Keycloak token with audience)
   - Phoenix traces for LLM calls
   - Kiali showing mTLS between agents
   - AuthBridge validation at each boundary
5. **Security verification:**
   - Attempt direct crawler access → 401 (no valid token)
   - Attempt query agent to write → 403 (read-only scope)
   - Attempt peer reviewer to access internet → Network policy block

---

### 2. **DevOps Incident Response & Remediation Platform**

**Overview:** Event-driven multi-agent system that detects, analyzes, and remediates production incidents with graduated privilege escalation.

#### Agent Architecture

```
Monitoring System (Prometheus Alert)
         │
         │ Webhook Event
         ▼
┌────────────────────────┐
│  Event Trigger System  │ (Kagenti Triggers)
└───────────┬────────────┘
            │ Spawns
            ▼
┌───────────────────────────────────────────────────┐
│  Triage Agent (team-sre/incident-triage)          │
│  - Analyzes alert severity (P0/P1/P2)             │
│  - Gathers context (logs, metrics, traces)        │
│  - Classifies incident type (memory/disk/network) │
│  - Outputs diagnostic report with root cause      │
│  SPIFFE: spiffe://kagenti.io/ns/team-sre/sa/triage│
└──────┬──────────────────┬─────────────────┬───────┘
       │                  │                 │
       ▼                  ▼                 ▼
┌──────────────┐  ┌───────────────┐  ┌──────────────┐
│Log Analysis  │  │Metric Analysis│  │ Trace        │
│Agent         │  │Agent          │  │ Analysis     │
│(read-only)   │  │(read-only)    │  │ Agent        │
│              │  │               │  │ (read-only)  │
└──────┬───────┘  └───────┬───────┘  └──────┬───────┘
       │                  │                  │
       │ Findings         │ Findings         │ Findings
       └──────────────────┴──────────────────┘
                          │
                          ▼
              ┌─────────────────────────────┐
              │ Decision Agent              │
              │ (team-sre)                  │
              │ - Evaluates remediation     │
              │   options from runbook      │
              │ - Proposes specific action  │
              │ - Calculates risk/impact    │
              │ - Requests human approval   │
              └──────────┬──────────────────┘
                         │
                         │ If approved
                         ▼
              ┌─────────────────────┐
              │ Remediation Agent   │
              │ (team-sre-privileged)│
              │ - K8s API access    │
              │ - Can restart pods  │
              │ - Can scale         │
              │ SPIFFE: ...sa/remediation
              │ Keycloak: remediation-write
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │ Post-Mortem Agent   │
              │ - Creates incident  │
              │   report in Jira    │
              │ - Updates runbook   │
              └─────────────────────┘
```

#### Identity & Permission Boundaries

**Triage Agent (Diagnosis Phase)**
- **Permissions:** Read Prometheus, read Elasticsearch, read Jaeger, call analysis agents
- **No write access** to production systems
- **No K8s API access** (can't even list pods)
- **Audience:** `prometheus-api`, `elasticsearch-api`, `jaeger-api`
- **Output:** Diagnostic report only (JSON with findings)

**Analysis Agents (Investigation Phase)**
- **Log Agent:** Read-only Elasticsearch
- **Metric Agent:** Read-only Prometheus
- **Trace Agent:** Read-only Jaeger
- **No cross-access** (log agent can't read metrics)
- **Output:** Structured findings (specific error messages, metrics thresholds exceeded)

**Decision Agent (Solution Design Phase)**
- **Permissions:** 
  - Read K8s API (metadata only: deployments, pods, services)
  - Read runbook database
  - Read historical incident database
- **No write access** to K8s or production
- **Audience:** `k8s-api-read`, `runbook-db`, `incident-db`
- **Logic:** 
  - Receives diagnostic report from Triage
  - Queries runbook for matching incident patterns
  - Proposes specific kubectl command with parameters
  - Requests approval via Slack with full context

**Remediation Agent (Execution Phase)**
- **Activation:** Only receives token after human approval
- **Elevated permissions:** Kubernetes API write access (limited operations + namespaces)
  - Allowed: `rollout restart`, `scale`, `delete pod`, `apply -f` (specific paths)
  - Denied: `delete namespace`, `delete pv`, `apply rolebinding`
- **Short-lived token** (120s) granted after approval, single-use
- **Audience:** `k8s-api-limited-write`
- **Actions logged** to immutable audit trail in real-time
- **Validation:** Checks service health after action, reports back
- **No decision-making** - only executes exact command from Decision Agent

#### Kagenti Features Demonstrated

✅ **Eventing:** Webhook trigger → agent activation  
✅ **Identity:** Separate identities for read vs write agents  
✅ **Trust:** Human-in-the-loop approval for privileged actions  
✅ **Access Control:** Graduated permissions (read → analyze → remediate)  
✅ **Observability:** Full trace of incident → resolution  
✅ **Multi-Agent:** 6-agent collaboration with different trust levels  

#### Demo Scenario

1. **Alert fires:** "High memory usage on payment-service"
2. **Trigger activates** triage agent automatically
3. **Triage agent:**
   - Fetches logs via Log Analysis agent
   - Fetches metrics via Metric Analysis agent
   - Identifies: memory leak in payment-service-v2.3.1
4. **Decision agent proposes:** "Restart payment-service pods"
5. **Approval requested** via Slack (shows SPIFFE ID, proposed action)
6. **SRE approves** → Remediation agent receives time-limited token
7. **Remediation agent:**
   - Token exchange: triage token → k8s-api token (aud: k8s-api-limited)
   - Executes: `kubectl rollout restart deployment payment-service -n production`
   - Returns success
8. **Post-mortem agent:**
   - Creates Jira ticket with full trace
   - Updates runbook in Confluence

**Security Validation:**
- Attempt remediation without approval → 403 (no token)
- Attempt triage agent to restart pods directly → 403 (insufficient scope)
- Attempt log agent to read metrics → 403 (wrong audience)

---

### 3. **Financial Trading Research & Compliance Platform**

**Overview:** Multi-domain agent system where different agents operate in separate trust zones with strict compliance requirements.

#### Trust Zones

```
┌────────────────────────────────────────────────────┐
│  Public Zone (team-research)                       │
│  - Market data agents (external APIs)              │
│  - News scraping agents                            │
│  - Public filings agents                           │
│  Identity: spiffe://kagenti.io/ns/team-research/*  │
│  No access to internal systems                     │
└────────────────────────────────────────────────────┘
                        │
                        │ One-way data flow
                        ▼
┌────────────────────────────────────────────────────┐
│  Analysis Zone (team-quant)                        │
│  - Quantitative analysis agents                    │
│  - ML model agents                                 │
│  - Portfolio optimization agents                   │
│  Identity: spiffe://kagenti.io/ns/team-quant/*     │
│  Can read public data, write to internal DB        │
└────────────────────────────────────────────────────┘
                        │
                        │ Compliance check
                        ▼
┌────────────────────────────────────────────────────┐
│  Compliance Zone (team-compliance)                 │
│  - Regulatory check agent                          │
│  - Risk assessment agent                           │
│  - Audit trail agent                               │
│  Identity: spiffe://kagenti.io/ns/team-compliance/*│
│  Read all zones, write compliance DB               │
└────────────────────────────────────────────────────┘
                        │
                        │ If approved
                        ▼
┌────────────────────────────────────────────────────┐
│  Trading Zone (team-trading)                       │
│  - Execution agent                                 │
│  - Order management agent                          │
│  Identity: spiffe://kagenti.io/ns/team-trading/*   │
│  Write to trading platform API (privileged)        │
└────────────────────────────────────────────────────┘
```

#### Kagenti Features Demonstrated

✅ **Multi-namespace isolation** (4 teams with different trust levels)  
✅ **One-way data flows** enforced by network policies + token audiences  
✅ **Compliance audit trails** via observability  
✅ **Graduated privileges** (read public → analyze → compliance check → execute)  
✅ **Token audience scoping** prevents cross-zone access  

---

### 4. **Healthcare Patient Care Coordination (HIPAA Compliance)**

**Overview:** Multi-agent healthcare system with strict privacy controls where each agent operates under "minimum necessary" access rules, patient consent is enforced via token scoping, and every access to Protected Health Information (PHI) is audited.

**Real-World Problem:** Healthcare organizations struggle with:
- 💊 Multiple systems that don't talk to each other (EHR, pharmacy, insurance, lab)
- 🔐 HIPAA violations from over-privileged access
- 📋 Manual coordination between departments
- 🏥 Poor patient experience (repeat same info to every provider)
- 📊 Difficult to audit who accessed what patient data

**Solution:** Multi-agent system where each agent has access to only the specific patient data needed for its function, with patient consent embedded in authentication tokens.

---

#### Agent Architecture

```
                     Patient Portal (User)
                     Patient: John Smith (ID: P-12345)
                     Grants consent: View medical history
                            │
                            │ JWT (aud: kagenti-ui)
                            │ claims: {patient_id: P-12345, consent: ["demographics", "appointments", "conditions"]}
                            ▼
        ┌───────────────────────────────────────────────┐
        │  Care Coordinator Agent                        │
        │  (team-care-coordination/care-coordinator)     │
        │  - Receives patient request                    │
        │  - Orchestrates workflow                       │
        │  - Delegates to specialist agents              │
        │  - NO direct PHI access                        │
        │  SPIFFE: spiffe://kagenti.io/ns/team-care-     │
        │          coordination/sa/care-coordinator      │
        └────┬──────────┬───────────┬────────────┬───────┘
             │          │           │            │
             │ Token    │ Token     │ Token      │ Token
             │ Exchange │ Exchange  │ Exchange   │ Exchange
             ▼          ▼           ▼            ▼
    ┌────────────┐ ┌─────────┐ ┌──────────┐ ┌──────────────┐
    │Appointment │ │ Medical │ │Prescription│ │  Insurance   │
    │ Scheduler  │ │ Records │ │   Agent    │ │ Verification │
    │   Agent    │ │  Agent  │ │            │ │    Agent     │
    │            │ │         │ │            │ │              │
    │ (team-     │ │(team-   │ │(team-      │ │(team-billing)│
    │ scheduling)│ │clinical)│ │clinical)   │ │              │
    └─────┬──────┘ └────┬────┘ └─────┬──────┘ └──────┬───────┘
          │             │            │               │
          ▼             ▼            ▼               ▼
    ┌──────────┐  ┌─────────┐  ┌─────────┐  ┌──────────────┐
    │Calendar  │  │  EHR    │  │Pharmacy │  │  Insurance   │
    │   API    │  │  FHIR   │  │   API   │  │     API      │
    │          │  │  Server │  │         │  │              │
    └──────────┘  └─────────┘  └─────────┘  └──────────────┘
                       │
                       ▼
              ┌──────────────────┐
              │  Audit Logger    │
              │  Agent           │
              │  (team-audit)    │
              │  - Logs all PHI  │
              │    access        │
              │  - Immutable log │
              └──────────────────┘
```

---

#### Agent Details & Identity Boundaries

**Care Coordinator Agent (Orchestration - No PHI)**
- **Identity:** `spiffe://kagenti.io/ns/team-care-coordination/sa/care-coordinator`
- **Purpose:** Orchestrate patient care workflows without touching PHI directly
- **Permissions:**
  - ✅ Can call other agents via A2A protocol
  - ✅ Can read workflow definitions
  - ❌ Cannot read EHR, prescriptions, or billing data
  - ❌ No PHI access at all
- **Token Audience:** `workflow-api`, `agent-orchestration`
- **Why separate:** Orchestration logic doesn't need PHI; keeps this agent simple and auditable

---

**Appointment Scheduler Agent (team-scheduling namespace)**
- **Identity:** `spiffe://kagenti.io/ns/team-scheduling/sa/appointment-scheduler`
- **Purpose:** Schedule appointments, manage calendar
- **Permissions:**
  - ✅ Calendar API - READ/WRITE (available slots, booked appointments)
  - ✅ Patient demographics - READ (name, date of birth, contact info)
  - ✅ Provider availability - READ
  - ❌ Cannot read: Medical history, diagnoses, medications, lab results
- **Token Audience:** `calendar-api`, `demographics-api-readonly`
- **Token Claims Required:** `patient_id`, `consent: ["demographics", "appointments"]`
- **Example PHI Access:**
  ```
  Can see: John Smith, DOB: 1975-03-15, Phone: 555-1234
  Cannot see: Diabetes diagnosis, Metformin prescription
  ```
- **Audit Log Entry:**
  ```
  timestamp: 2026-05-19T10:30:00Z
  agent: appointment-scheduler
  spiffe_id: spiffe://kagenti.io/ns/team-scheduling/sa/appointment-scheduler
  action: READ_DEMOGRAPHICS
  patient_id: P-12345
  fields_accessed: [name, dob, phone]
  purpose: appointment_scheduling
  consent_granted: true
  user_identity: john.smith@email.com
  ```

---

**Medical Records Agent (team-clinical namespace)**
- **Identity:** `spiffe://kagenti.io/ns/team-clinical/sa/medical-records`
- **Purpose:** Retrieve and summarize patient medical history
- **Permissions:**
  - ✅ EHR API - READ (FHIR resources: Condition, Observation, Procedure)
  - ✅ Can access: Diagnoses, conditions, treatment history
  - ❌ Cannot write to EHR (read-only for AI agents)
  - ❌ Cannot access: Billing information, insurance claims
- **Token Audience:** `ehr-api-readonly-patient-{patient_id}`
- **Token Claims Required:** 
  ```json
  {
    "patient_id": "P-12345",
    "consent": ["conditions", "medical_history"],
    "purpose": "care_coordination"
  }
  ```
- **HIPAA "Minimum Necessary" Enforcement:**
  - Token audience is **patient-specific**: `ehr-api-readonly-patient-P-12345`
  - Agent cannot request data for different patient (token validation fails)
  - Token expires in 300 seconds
- **Example PHI Access:**
  ```
  Can see: 
    - Condition: Type 2 Diabetes (diagnosed 2020-03-15)
    - Observation: HbA1c 7.2% (2026-04-01)
    - Procedure: Annual physical exam (2026-04-15)
  
  Cannot see:
    - Insurance claims
    - Payment information
    - Psychiatric notes (requires separate consent)
  ```
- **Audit Log Entry:**
  ```
  timestamp: 2026-05-19T10:31:15Z
  agent: medical-records
  spiffe_id: spiffe://kagenti.io/ns/team-clinical/sa/medical-records
  action: READ_FHIR_RESOURCES
  patient_id: P-12345
  resources_accessed: [Condition/123, Observation/456, Procedure/789]
  token_audience: ehr-api-readonly-patient-P-12345
  consent_verified: true
  purpose: care_coordination
  requested_by_user: john.smith@email.com
  ip_address: 10.0.1.45
  session_id: SES-2026-051945
  ```

---

**Prescription Agent (team-clinical namespace)**
- **Identity:** `spiffe://kagenti.io/ns/team-clinical/sa/prescription-manager`
- **Purpose:** Manage prescriptions and send to pharmacy
- **Permissions:**
  - ✅ EHR API - READ (MedicationRequest resources only)
  - ✅ Pharmacy API - WRITE (send prescriptions)
  - ✅ Drug interaction database - READ (check for conflicts)
  - ❌ Cannot read: Full medical history, lab results, diagnoses
  - ❌ Cannot access: Billing, insurance
- **Token Audience:** `ehr-medications-patient-{patient_id}`, `pharmacy-api-write`
- **Token Claims Required:**
  ```json
  {
    "patient_id": "P-12345",
    "consent": ["medications", "prescriptions"],
    "provider_id": "DR-67890",
    "prescription_authority": true
  }
  ```
- **Security Boundary:** 
  - Can **only** see MedicationRequest resources (not Condition, Procedure, etc.)
  - Separate token for pharmacy write access
  - Drug interactions checked before sending to pharmacy
- **Example Workflow:**
  ```
  Input: Doctor prescribes Lisinopril 10mg for patient P-12345
  
  Step 1: Read current medications from EHR
    Current meds: Metformin 500mg (diabetes)
  
  Step 2: Check drug interactions
    Lisinopril + Metformin: No interactions ✓
  
  Step 3: Send to pharmacy API
    Token exchange: ehr-token → pharmacy-api-write token
    Submit: Lisinopril 10mg, 30-day supply, Dr. Johnson
  
  Step 4: Audit
    Log: Prescription sent for patient P-12345
  ```
- **Cannot Access:**
  ```
  ✗ Why is patient taking Metformin? (Diabetes diagnosis - separate resource)
  ✗ Patient's blood pressure readings (Observations - separate resource)
  ✗ Insurance coverage for Lisinopril (Billing data - different namespace)
  ```

---

**Insurance Verification Agent (team-billing namespace)**
- **Identity:** `spiffe://kagenti.io/ns/team-billing/sa/insurance-verification`
- **Purpose:** Verify insurance coverage and eligibility
- **Permissions:**
  - ✅ Insurance API - READ (coverage, eligibility)
  - ✅ Patient billing info - READ (insurance ID, member number)
  - ❌ Cannot access: Clinical data (diagnoses, medications, procedures)
  - ❌ Cannot access: EHR at all
- **Token Audience:** `insurance-api-readonly`, `billing-info-patient-{patient_id}`
- **Token Claims Required:**
  ```json
  {
    "patient_id": "P-12345",
    "consent": ["insurance_verification"],
    "purpose": "eligibility_check"
  }
  ```
- **Network Policy:** Cannot reach clinical namespace at all (Kubernetes NetworkPolicy blocks traffic)
- **Example Access:**
  ```
  Can see:
    - Insurance: Blue Cross Blue Shield
    - Policy Number: BCBS-12345678
    - Coverage: Active
    - Copay: $25 for specialist visit
  
  Cannot see:
    - Why patient is visiting (diagnosis)
    - What medications patient takes
    - Any clinical information
  ```
- **Security Property:** Even if compromised, this agent **physically cannot** access clinical data (network isolation + no EHR tokens)

---

**Audit Logger Agent (team-audit namespace)**
- **Identity:** `spiffe://kagenti.io/ns/team-audit/sa/audit-logger`
- **Purpose:** Centralized, immutable audit logging for HIPAA compliance
- **Permissions:**
  - ✅ Can read: All agent activity (receives logs from all namespaces)
  - ✅ Can write: Immutable audit log (append-only database)
  - ❌ Cannot read: Actual PHI (only logs metadata about access)
  - ❌ Cannot modify: Historical audit records
- **Log Format:**
  ```json
  {
    "timestamp": "2026-05-19T10:31:15.234Z",
    "event_id": "EVT-2026-051945-0001",
    "agent_name": "medical-records",
    "spiffe_id": "spiffe://kagenti.io/ns/team-clinical/sa/medical-records",
    "action": "READ_FHIR_RESOURCES",
    "patient_id": "P-12345",
    "patient_name_hash": "SHA256:a3d8f...",
    "resources_accessed": [
      "Condition/123 (Type2Diabetes)",
      "Observation/456 (HbA1c)",
      "Procedure/789 (AnnualPhysical)"
    ],
    "token_audience": "ehr-api-readonly-patient-P-12345",
    "token_claims": {
      "consent": ["conditions", "medical_history"],
      "purpose": "care_coordination"
    },
    "consent_verified": true,
    "user_identity": "john.smith@email.com",
    "user_ip": "10.0.1.45",
    "session_id": "SES-2026-051945",
    "result": "SUCCESS",
    "fields_returned": 47,
    "duration_ms": 234
  }
  ```
- **HIPAA Requirement Met:** 
  - **45 CFR § 164.308(a)(1)(ii)(D)** - Information system activity review
  - **45 CFR § 164.312(b)** - Audit controls
  - Logs retained for 6 years (HIPAA minimum)
  - Immutable (cannot be altered or deleted)

---

#### Complete Patient Care Scenario

**Scenario:** Patient John Smith visits his doctor for a diabetes checkup and needs a prescription refill.

---

**Step 1: Patient Authentication & Consent (10:30:00)**
```
Patient Portal:
  User: john.smith@email.com
  Patient ID: P-12345
  
  Patient grants consent:
  ☑ View my medical history
  ☑ View my medications
  ☑ Send prescriptions to my pharmacy
  ☑ Verify my insurance
  
Keycloak issues JWT:
  {
    "sub": "john.smith@email.com",
    "patient_id": "P-12345",
    "consent": ["demographics", "appointments", "conditions", 
                "medical_history", "medications", "prescriptions", 
                "insurance_verification"],
    "aud": "kagenti-ui",
    "exp": 1716115800,
    "iss": "https://keycloak.hospital.local/realms/healthcare"
  }
```

---

**Step 2: Care Coordinator Receives Request (10:30:15)**
```
Patient request: "Schedule follow-up appointment and refill Metformin"

Care Coordinator Agent:
  - Receives JWT from patient
  - Validates patient consent in token
  - Identifies needed workflow:
    1. Check appointment availability
    2. Review current medications
    3. Send prescription to pharmacy
    4. Verify insurance coverage
  
  - Delegates to specialized agents (A2A protocol)
```

---

**Step 3: Appointment Scheduler Agent (10:30:20)**
```
Care Coordinator → Appointment Scheduler:
  Token exchange: kagenti-ui token → calendar-api token
  
Appointment Scheduler Agent:
  Identity: spiffe://kagenti.io/ns/team-scheduling/sa/appointment-scheduler
  Token audience: calendar-api, demographics-api-readonly-patient-P-12345
  
  Action 1: Read patient demographics
    → Name: John Smith
    → DOB: 1975-03-15
    → Phone: 555-1234
    → Email: john.smith@email.com
  
  Action 2: Query calendar API
    → Available slots with Dr. Johnson (endocrinologist)
    → Next available: 2026-05-26 at 2:00 PM
  
  Action 3: Book appointment
    → Appointment ID: APT-2026-052619
    → Confirmation sent to patient
  
  Result: ✓ Appointment scheduled

Audit Log:
  agent: appointment-scheduler
  action: [READ_DEMOGRAPHICS, BOOK_APPOINTMENT]
  patient_id: P-12345
  fields_accessed: [name, dob, phone, email]
  result: SUCCESS
```

---

**Step 4: Medical Records Agent (10:30:35)**
```
Care Coordinator → Medical Records Agent:
  Token exchange: kagenti-ui token → ehr-api-readonly-patient-P-12345 token
  
Medical Records Agent:
  Identity: spiffe://kagenti.io/ns/team-clinical/sa/medical-records
  Token audience: ehr-api-readonly-patient-P-12345
  Token contains consent: ["conditions", "medical_history"]
  
  Action 1: Read patient conditions from EHR (FHIR)
    GET /Patient/P-12345/Condition
    
    Results:
    - Condition/123: Type 2 Diabetes Mellitus
      Onset: 2020-03-15
      Status: Active
      Severity: Moderate
    
    - Condition/124: Hypertension
      Onset: 2018-06-01
      Status: Active
      Severity: Mild
  
  Action 2: Read recent observations
    GET /Patient/P-12345/Observation?date=gt2026-01-01
    
    Results:
    - Observation/456: HbA1c = 7.2% (2026-04-01)
      Reference range: <7.0% (goal for diabetes)
    
    - Observation/457: Blood Pressure = 128/82 (2026-04-01)
      Reference range: <130/80
  
  Result: Summary for provider
    "Patient has well-controlled Type 2 Diabetes (HbA1c 7.2%) 
     and hypertension. Last checkup 6 weeks ago."

Audit Log:
  agent: medical-records
  action: READ_FHIR_RESOURCES
  patient_id: P-12345
  resources_accessed: [Condition/123, Condition/124, Observation/456, Observation/457]
  token_audience: ehr-api-readonly-patient-P-12345
  consent_verified: true
  result: SUCCESS
  duration_ms: 234
```

---

**Step 5: Prescription Agent (10:30:50)**
```
Care Coordinator → Prescription Agent:
  Token exchange: kagenti-ui token → ehr-medications-patient-P-12345 token
  Provider approved: Dr. Johnson (ID: DR-67890)
  
Prescription Agent:
  Identity: spiffe://kagenti.io/ns/team-clinical/sa/prescription-manager
  Token audience: ehr-medications-patient-P-12345, pharmacy-api-write
  Token contains: prescription_authority: true, provider_id: DR-67890
  
  Action 1: Read current medications
    GET /Patient/P-12345/MedicationRequest?status=active
    
    Results:
    - MedicationRequest/789: Metformin 500mg
      Dosage: Twice daily with meals
      Quantity: 60 tablets
      Refills remaining: 0 (NEEDS REFILL)
      Last filled: 2026-04-19
      Prescriber: Dr. Johnson
  
  Action 2: Check drug interactions
    Query drug database:
      Current: Metformin 500mg
      Proposed refill: Metformin 500mg (same)
      Interactions: None ✓
  
  Action 3: Create new prescription
    POST /MedicationRequest
    {
      "patient": "P-12345",
      "medication": "Metformin 500mg",
      "dosage": "1 tablet twice daily with meals",
      "quantity": 60,
      "refills": 3,
      "prescriber": "DR-67890",
      "pharmacy": "Walgreens #4523"
    }
    
    Result: MedicationRequest/790 created
  
  Action 4: Send to pharmacy (token exchange required)
    Exchange token: ehr-medications → pharmacy-api-write
    
    POST to Pharmacy API (Walgreens):
    {
      "prescription_id": "RX-2026-051945",
      "patient": "John Smith",
      "dob": "1975-03-15",
      "medication": "Metformin 500mg",
      "quantity": 60,
      "directions": "Take 1 tablet twice daily with meals",
      "refills": 3,
      "prescriber": "Dr. Sarah Johnson, MD",
      "prescriber_npi": "1234567890",
      "pharmacy_location": "4523"
    }
    
    Pharmacy Response:
    {
      "status": "ACCEPTED",
      "ready_date": "2026-05-19",
      "ready_time": "16:00",
      "copay": "$10.00"
    }
  
  Result: ✓ Prescription sent to pharmacy

Audit Log:
  agent: prescription-manager
  action: [READ_MEDICATIONS, CREATE_PRESCRIPTION, SEND_TO_PHARMACY]
  patient_id: P-12345
  medication: Metformin 500mg
  prescriber: DR-67890
  pharmacy: Walgreens-4523
  token_audiences: [ehr-medications-patient-P-12345, pharmacy-api-write]
  result: SUCCESS
```

---

**Step 6: Insurance Verification Agent (10:31:10)**
```
Care Coordinator → Insurance Verification Agent:
  Token exchange: kagenti-ui token → insurance-api-readonly token
  
Insurance Verification Agent:
  Identity: spiffe://kagenti.io/ns/team-billing/sa/insurance-verification
  Token audience: insurance-api-readonly, billing-info-patient-P-12345
  
  NOTE: This agent has NO access to clinical namespace (NetworkPolicy blocks it)
  
  Action 1: Read patient insurance info
    GET /Patient/P-12345/Coverage
    
    Result:
    - Insurance: Blue Cross Blue Shield
    - Policy: BCBS-12345678
    - Group: GRP-99999
    - Status: Active
    - Effective: 2026-01-01 to 2026-12-31
  
  Action 2: Verify eligibility with insurance API
    POST to Insurance API:
    {
      "member_id": "BCBS-12345678",
      "service_type": "office_visit",
      "service_date": "2026-05-26",
      "provider_npi": "1234567890"
    }
    
    Insurance Response:
    {
      "eligible": true,
      "copay": "$25.00",
      "deductible_met": true,
      "coverage_level": "in_network"
    }
  
  Result: ✓ Insurance verified, $25 copay

Audit Log:
  agent: insurance-verification
  action: [READ_COVERAGE, VERIFY_ELIGIBILITY]
  patient_id: P-12345
  insurance_policy: BCBS-12345678
  service_date: 2026-05-26
  result: ELIGIBLE
  copay: $25.00
  
  NOTE: Log contains NO clinical information (agent never accessed EHR)
```

---

**Step 7: Final Report to Patient (10:31:20)**
```
Care Coordinator Agent:
  Aggregates results from all agents:
  
  ✓ Appointment: May 26, 2026 at 2:00 PM with Dr. Johnson
  ✓ Prescription: Metformin refill sent to Walgreens #4523
                  Ready for pickup today at 4:00 PM
  ✓ Insurance: Verified, $25 copay for office visit
  ✓ Medical Summary: Diabetes well-controlled (HbA1c 7.2%)
  
  Sends confirmation to patient portal + email
```

---

**Step 8: Audit Trail (Continuous)**
```
Audit Logger Agent has recorded entire workflow:

Summary for Patient P-12345 session SES-2026-051945:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Timestamp: 2026-05-19 10:30:00 to 10:31:20 (80 seconds)
User: john.smith@email.com
Patient ID: P-12345
Consent granted: demographics, appointments, conditions, 
                 medical_history, medications, prescriptions,
                 insurance_verification

AGENTS ACCESSED PHI:
┌─────────────────────┬──────────────┬─────────────────┐
│ Agent               │ PHI Accessed │ Purpose         │
├─────────────────────┼──────────────┼─────────────────┤
│ appointment-        │ demographics │ Schedule appt   │
│ scheduler           │              │                 │
├─────────────────────┼──────────────┼─────────────────┤
│ medical-records     │ conditions,  │ Review history  │
│                     │ observations │                 │
├─────────────────────┼──────────────┼─────────────────┤
│ prescription-       │ medications  │ Refill Rx       │
│ manager             │              │                 │
├─────────────────────┼──────────────┼─────────────────┤
│ insurance-          │ coverage,    │ Verify benefits │
│ verification        │ billing      │                 │
└─────────────────────┴──────────────┴─────────────────┘

ACTIONS TAKEN:
• READ_DEMOGRAPHICS (appointment-scheduler)
• BOOK_APPOINTMENT (appointment-scheduler)
• READ_FHIR_RESOURCES: Condition/123, Condition/124, 
  Observation/456, Observation/457 (medical-records)
• READ_MEDICATIONS: MedicationRequest/789 (prescription-manager)
• CREATE_PRESCRIPTION: MedicationRequest/790 (prescription-manager)
• SEND_TO_PHARMACY: Walgreens-4523 (prescription-manager)
• READ_COVERAGE (insurance-verification)
• VERIFY_ELIGIBILITY (insurance-verification)

ALL ACCESSES: ✓ AUTHORIZED (patient consent verified)
TOKEN EXPIRATION: All tokens <5 minutes lifetime
SPIFFE IDS: All agents authenticated
RESULT: SUCCESS

Audit trail stored in immutable log (retention: 6 years per HIPAA)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

#### Security Validation Scenarios

**Scenario 1: Agent Tries to Access Wrong Patient**

```
Prescription Agent attempts:
  GET /Patient/P-99999/MedicationRequest
  (Different patient ID than token allows)

AuthBridge (Inbound Validation):
  Token audience: ehr-medications-patient-P-12345
  Requested resource: Patient P-99999
  
  ✗ MISMATCH: Token is for P-12345, not P-99999
  
  Response: 403 Forbidden
  Audit log: UNAUTHORIZED_ACCESS_ATTEMPT
             agent: prescription-manager
             requested: P-99999
             authorized_for: P-12345
             result: DENIED
```

**Scenario 2: Insurance Agent Tries to Access Clinical Data**

```
Insurance Verification Agent attempts:
  GET /Patient/P-12345/Condition
  (Trying to see diagnoses)

Kubernetes NetworkPolicy:
  Source: team-billing namespace
  Destination: EHR FHIR server (team-clinical namespace)
  
  ✗ NETWORK POLICY DENIES traffic from billing to clinical
  
  Response: Connection timeout (no route)
  Audit log: NETWORK_POLICY_VIOLATION
             source_agent: insurance-verification
             attempted_destination: ehr-fhir-server
             reason: namespace_isolation_policy
             result: BLOCKED
```

**Scenario 3: Expired Token**

```
Medical Records Agent attempts access:
  GET /Patient/P-12345/Condition
  
Token issued at: 10:30:15
Token expires at: 10:35:15 (5 minutes)
Current time: 10:36:00

AuthBridge (Inbound Validation):
  ✗ Token expired 45 seconds ago
  
  Response: 401 Unauthorized
  Message: "Token expired, please re-authenticate"
  Audit log: EXPIRED_TOKEN
             agent: medical-records
             expired_at: 10:35:15
             attempted_at: 10:36:00
             result: DENIED
```

**Scenario 4: Patient Revokes Consent Mid-Session**

```
10:30:00 - Patient grants consent for medications
10:30:50 - Prescription Agent accesses medications ✓
10:31:00 - Patient revokes "medications" consent
10:31:30 - Prescription Agent tries to access again

Consent Service:
  Patient P-12345 consent status at 10:31:30:
    medications: REVOKED (as of 10:31:00)
  
AuthBridge:
  ✗ Consent no longer valid
  
  Response: 403 Forbidden
  Message: "Patient consent revoked"
  Audit log: CONSENT_REVOKED
             patient: P-12345
             consent_type: medications
             revoked_at: 10:31:00
             attempted_access: 10:31:30
             result: DENIED
  
  Notification: Patient portal shows "Access denied (consent revoked)"
```

---

#### HIPAA Compliance Features Demonstrated

| HIPAA Requirement | How Kagenti Implements It |
|-------------------|---------------------------|
| **§164.308(a)(3) - Workforce access** | Each agent has unique SPIFFE ID, minimum necessary access |
| **§164.308(a)(4) - Access controls** | Token audiences scope access to specific patient + data type |
| **§164.312(a)(1) - Unique user ID** | SPIFFE IDs are cryptographically unique per agent |
| **§164.312(b) - Audit controls** | Audit Logger Agent records all PHI access (immutable) |
| **§164.312(c)(1) - Integrity controls** | Tokens are cryptographically signed, cannot be forged |
| **§164.312(d) - Person/entity authentication** | SPIRE workload attestation + Keycloak user auth |
| **§164.312(e)(1) - Transmission security** | Istio Ambient mTLS for all inter-agent communication |
| **§164.502(b) - Minimum necessary** | Each agent sees only specific data needed for its function |
| **§164.524 - Right of access** | Patient can view audit log of who accessed their data |
| **§164.528 - Accounting of disclosures** | Audit log provides complete disclosure history |

**Audit Report Example (Patient Request):**
```
Patient John Smith requests: "Who has accessed my medical records?"

Audit Logger Agent generates report:

Your Health Information Access Report
Patient: John Smith (P-12345)
Date Range: Last 30 days

┌────────────┬─────────────────────┬────────────────┬──────────┐
│ Date       │ Who                 │ What Accessed  │ Purpose  │
├────────────┼─────────────────────┼────────────────┼──────────┤
│ 2026-05-19 │ Dr. Sarah Johnson   │ Full record    │ Office   │
│ 10:30      │                     │                │ visit    │
├────────────┼─────────────────────┼────────────────┼──────────┤
│ 2026-05-19 │ Medical Records     │ Conditions,    │ Care     │
│ 10:30      │ Agent (AI)          │ observations   │ coord.   │
├────────────┼─────────────────────┼────────────────┼──────────┤
│ 2026-05-19 │ Prescription Agent  │ Medications    │ Rx refill│
│ 10:30      │ (AI)                │ only           │          │
├────────────┼─────────────────────┼────────────────┼──────────┤
│ 2026-05-15 │ Lab Technician      │ Lab orders     │ Blood    │
│ 09:15      │ (Maria Lopez)       │                │ draw     │
├────────────┼─────────────────────┼────────────────┼──────────┤
│ 2026-05-12 │ Billing Dept        │ Insurance info │ Claim    │
│ 14:20      │ (System)            │ only           │ filing   │
└────────────┴─────────────────────┴────────────────┴──────────┘

All accesses were authorized by your consent.
To revoke consent, visit: Patient Portal > Privacy > Manage Consent
```

---

#### Kagenti Features Demonstrated

✅ **Identity & SPIFFE:**
- Each agent has cryptographically verifiable SPIFFE ID
- Workload attestation via SPIRE
- No static credentials (dynamic identity)

✅ **Fine-Grained Access Control:**
- Patient-specific token audiences: `ehr-api-readonly-patient-P-12345`
- Data-type scoping: medications vs conditions vs billing
- Time-limited tokens (5 minutes)
- Consent embedded in token claims

✅ **Trust Boundaries:**
- 4 namespaces with different trust levels (scheduling, clinical, billing, audit)
- Network policies enforce isolation
- No agent can access data outside its scope

✅ **Token Exchange:**
```
Patient JWT (aud: kagenti-ui)
  ↓ exchange
Medical Records Agent token (aud: ehr-api-readonly-patient-P-12345)
  ↓ exchange
Prescription Agent token (aud: pharmacy-api-write)
```

✅ **Audit Trail:**
- Every PHI access logged with SPIFFE ID
- Immutable audit log (append-only)
- 6-year retention (HIPAA requirement)
- Patient can view their own access log

✅ **Multi-Agent Collaboration:**
- 5 agents coordinate via A2A protocol
- Care Coordinator orchestrates without PHI access
- Each agent specializes in one function

✅ **Zero-Trust:**
- No implicit trust between agents
- Continuous authentication at every hop
- Consent verified on every access
- Network isolation between trust zones

✅ **Observability:**
- OpenTelemetry traces show complete workflow
- Phoenix (if enabled) traces LLM reasoning
- Kiali visualizes service mesh traffic

✅ **Compliance:**
- HIPAA §164.308, §164.312 requirements met
- Patient consent enforcement
- Right of access (audit reports)
- Minimum necessary principle  

---

## Comparison Matrix

| Use Case | Identity Demo | Access Control Demo | Trust Demo | Multi-Agent | Observability | Eventing | Complexity |
|----------|---------------|---------------------|------------|-------------|---------------|----------|------------|
| **Research Platform** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | High |
| **DevOps Incident** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Medium |
| **Financial Trading** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | High |
| **Healthcare** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | High |

---

## Recommendation

**Top Choice: Academic Research Intelligence Platform (Enhanced)**

**Rationale:**
1. **Demonstrates ALL core features:** Identity, access control, trust boundaries, multi-agent collaboration, observability, and eventing
2. **Relatable:** Easy to explain to technical and non-technical audiences
3. **Real-world value:** Solves actual pain point for researchers
4. **Scalable demo:** Can start with 2 agents (crawler + query) and expand to 5+ agents
5. **Visual appeal:** Clear data flow, multiple trust zones, easy to diagram
6. **Multiple failure scenarios:** Easy to demonstrate security (try to bypass controls, inject malicious content, etc.)

**Runner-up: DevOps Incident Response**
- Equally strong on features
- More operational/SRE audience
- Requires more setup (Prometheus, alerts)
- Less intuitive for general audience

---

## Next Steps

1. **Review with team** - Which use case resonates?
2. **Design detailed architecture** - API contracts, data schemas, agent specs
3. **Identify existing code** - What can we reuse from kagenti/examples?
4. **Plan timeline** - Phased implementation (MVP → Full demo)
5. **Assign owners** - Who builds crawler, who builds peer review, etc.
