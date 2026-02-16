# Agent Attestation Framework Proposal

## Cloud-Native AI Agent Trust and Integrity Verification

| | |
|---|---|
| **Version** | 1.0 Draft |
| **Date** | February 2, 2026 |
| **Status** | Proposal |
| **Related Epic** | [TBD - Create in kagenti/kagenti] |

---

## Goal

Extend the Kagenti platform with an **attestation layer** that provides cryptographic guarantees about agent integrity, provenance, and trustworthiness—complementing the existing AuthBridge authentication infrastructure.

**Key distinction:**
- **Authentication** (AuthBridge - existing): Proves *who* an agent is via SPIFFE/SPIRE + Keycloak
- **Attestation** (this proposal): Proves *what* an agent is and whether it can be trusted

---

## Background: Authentication vs. Attestation

### Why Attestation Is Needed Beyond Authentication

| Dimension | Authentication (Existing) | Attestation (Proposed) |
|-----------|--------------------------|------------------------|
| **Question** | "Who are you?" | "What are you? Can I trust you?" |
| **Mechanism** | SPIFFE SVIDs, OAuth tokens | Signatures, hashes, provenance |
| **Timing** | Every request (runtime) | Deployment + periodic |
| **Gap it fills** | Identity verification | Integrity & compliance verification |

**Without attestation:** A compromised agent with valid credentials can communicate freely.
**With attestation:** Compromised agents are blocked at deployment before authentication occurs.

### The 7 Categories of A2A Trust Signals

| # | Signal | Type | Implementation |
|---|--------|------|----------------|
| 1 | **Identity** | Authentication | ✅ SPIFFE/SPIRE (existing) |
| 2 | **Capability** | Attestation | 🔲 Admission webhook validation |
| 3 | **Policy** | Attestation | 🔲 OPA/Gatekeeper |
| 4 | **Provenance** | Attestation | 🔲 Sigstore/Cosign |
| 5 | **Endorsement** | Attestation | 🔲 Trust registry |
| 6 | **History** | Attestation | 🔲 OpenTelemetry audit |
| 7 | **Liveness** | Attestation | 🔲 Runtime attestor |

---

## Phase 1 – Foundation (Identity Binding & Provenance)

**Objective:** Establish basic attestation for agent integrity and supply chain verification.

### 1.1 Agent Card Integrity

* Add `kagenti.dev/agent-card-hash` annotation computation to CI pipeline.
* Implement hash verification in `ValidateCreate` admission webhook.
* Bind SPIFFE ID to Agent Card via annotation.
* Test Agent CR deployment with hash validation enforcement.

### 1.2 Image Provenance

* Integrate Cosign into GitHub Actions build workflow.
* Enable keyless signing via GitHub OIDC (Sigstore Fulcio).
* Generate and attach SBOM attestation (Syft + Cosign attest).
* Document signature verification process for operators.

### 1.3 Capability Validation

* Define allowed capabilities ConfigMap schema.
* Implement `validateCapabilities()` in admission webhook.
* Test rejection of unauthorized capability declarations.

**Deliverables:**
- All agent images cryptographically signed
- Agent Cards require hash annotation (enforced at admission)
- Unauthorized capabilities blocked at deployment

---

## Phase 2 – Governance (Policy & Audit)

**Objective:** Add policy-as-code enforcement and behavioral audit trail.

### 2.1 Policy Enforcement

* Deploy OPA Gatekeeper to cluster (update Ansible installer).
* Create `ConstraintTemplate` for agent capability limits.
* Define baseline agent policy constraints (rate limits, data classification).
* Integrate policy evaluation into admission webhook.

### 2.2 Audit Logging

* Deploy OpenTelemetry collector for agent interactions.
* Define audit event schema for A2A communications.
* Configure agent interaction logging via sidecar injection.
* Create behavioral alerting rules for anomaly detection.

**Deliverables:**
- Policy violations blocked at admission
- All agent interactions logged with full context
- Anomaly detection alerts configured

---

## Phase 3 – Advanced Attestation (Endorsement & Liveness)

**Objective:** Enable third-party trust endorsements and continuous runtime verification.

### 3.1 Endorsement Framework

* Define endorsement schema (issuer, signature, claims, expiry).
* Create trust registry ConfigMap for authorized issuers.
* Implement endorsement signature verification service.
* Add endorsement validation to admission webhook.

### 3.2 Runtime Liveness

* Build `runtime-attestor` sidecar container.
* Add runtime-attestor injection to webhook (optional per-agent).
* Implement periodic attestation generation (hash, SVID status, process list).
* Create liveness enforcement policies (stale attestation handling).

**Deliverables:**
- Third-party endorsements verified at admission
- Runtime integrity continuously monitored
- Stale attestations trigger quarantine/alert

---

## Phase 4 – Integration with Compositional API

**Objective:** Align attestation framework with Kagenti's compositional agent platform architecture.

* Integrate attestation with `TokenExchange` composition API.
* Extend `AgentCard` CRD to include attestation metadata.
* Add attestation events to `AgentTrace` observability API.
* Ensure attestation works with Deployment-based agents (post-Agent CRD removal).

**Reference:** [Epic #523 - Refactor Kagenti APIs for Compositional Architecture](https://github.com/kagenti/kagenti/issues/523)

---

## Architectural Principles

* **Attestation gates authentication:** Verify trust before identity is issued.
* **Non-blocking adoption:** Warning mode before enforcement; gradual rollout.
* **Layered trust:** Multiple independent attestations provide defense in depth.
* **Standards-based:** Use Sigstore, SLSA, SPIFFE—no proprietary attestation formats.
* **Kubernetes-native:** Leverage admission webhooks, CRDs, and existing Kagenti patterns.

---

## Technical Specifications

### Agent Card Hash Verification

```go
func (v *AgentCustomValidator) validateAgentCardHash(agent *Agent) error {
    declaredHash := agent.Annotations["kagenti.dev/agent-card-hash"]
    if declaredHash == "" {
        return fmt.Errorf("kagenti.dev/agent-card-hash annotation required")
    }
    
    cardBytes, _ := json.Marshal(agent.Spec.AgentCard)
    computedHash := fmt.Sprintf("sha256:%x", sha256.Sum256(cardBytes))
    
    if computedHash != declaredHash {
        return fmt.Errorf("agent card hash mismatch")
    }
    return nil
}
```

### Image Signing (CI Addition)

```yaml
# Add to .github/workflows/build.yaml
- name: Sign image with Cosign
  uses: sigstore/cosign-installer@v3
- run: |
    cosign sign --yes $IMAGE_REF
    syft $IMAGE_REF -o spdx-json > sbom.json
    cosign attest --predicate sbom.json --type spdx $IMAGE_REF
```

### Attestation Data Structure

```go
type AgentAttestation struct {
    SpiffeID         string        `json:"spiffeId"`
    AgentCardHash    string        `json:"agentCardHash"`
    ImageSignature   string        `json:"imageSignature"`
    SLSAProvenance   string        `json:"slsaProvenance"`
    Capabilities     []string      `json:"capabilities"`
    Endorsements     []Endorsement `json:"endorsements"`
    AttestationTime  time.Time     `json:"attestationTime"`
}
```

---

## Success Criteria

| Metric | Target |
|--------|--------|
| Image signing coverage | 100% of agent images signed |
| Hash validation enforcement | 100% of agents require hash annotation |
| Capability validation | Invalid capabilities rejected at admission |
| Verification latency | < 500ms added to deployment time |
| False positive rate | < 1% legitimate agents blocked |

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Sigstore availability | Cache signatures, allow grace period |
| Webhook latency | Async verification for non-critical checks |
| Backwards compatibility | Warning mode before enforcement |
| Complexity | Phased rollout, comprehensive documentation |

---

## References

* [AuthBridge README](./AuthBridge/README.md) - Current authentication implementation
* [Kagenti Webhook README](./kagenti-webhook/README.md) - Admission webhook documentation
* [Epic #523 - Compositional API Architecture](https://github.com/kagenti/kagenti/issues/523)
* [SPIFFE/SPIRE Documentation](https://spiffe.io/docs/latest/)
* [Sigstore/Cosign](https://docs.sigstore.dev/)
* [SLSA Framework](https://slsa.dev/)

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-02 | Initial draft |
