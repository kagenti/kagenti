# Versioned Skill Packs for Sandbox Agents

> **Date:** 2026-03-04
> **Author:** Session M (Chat UX Polish)
> **Status:** Approved
> **Depends on:** agent_server.py SkillsLoader, SandboxCreatePage wizard

## Problem

Sandbox agents start with empty `/workspace/.claude/skills/` — no skills are injected
by default. Users must manually configure skill sources. There is no mechanism to:

1. Pin skill packs to verified commits
2. Verify commit signatures or content integrity
3. Default to "superpowers" skills for new agents
4. Configure skill selection in the create-agent wizard

## Design

### Architecture

```
skill-packs.yaml (in repo, version-controlled)
    │
    ├── lists packs: name, git URL, commit hash, GPG key, content hash
    │
    └── read by:
         ├── Init Container (at agent pod startup)
         │    └── git clone → verify commit sig → verify content hash
         │         → copy to /workspace/.claude/skills/
         │
         └── Wizard UI (at create-agent time)
              └── Step 2: "Skills" — checkboxes, superpowers default
```

### 1. Manifest: `skill-packs.yaml`

Lives in repo root. Pinned skill sources with layered verification.

```yaml
# skill-packs.yaml — pinned, verified skill sources
version: 1

trusted_keys:
  - id: ladas
    fingerprint: "SHA256:AAAA..."
    type: ssh  # or gpg
  - id: anthropic-bot
    fingerprint: "SHA256:BBBB..."
    type: gpg

packs:
  - name: superpowers
    description: "Claude Code superpowers — brainstorming, TDD, debugging, code review"
    source: https://github.com/claude-plugins-official/superpowers
    commit: a1b2c3d4e5f6
    path: skills/
    integrity: "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    signer: anthropic-bot
    default: true

  - name: kagenti-ops
    description: "Kagenti platform operations — k8s, helm, hypershift, istio"
    source: https://github.com/Ladas/kagenti
    commit: c5ac7352
    path: .claude/skills/
    integrity: "sha256:abc123..."
    signer: ladas
    default: false
```

### 2. Init Container: `skill_pack_loader.py`

Added to agent pod spec by the deployment backend. Runs before the main
agent container starts.

**Verification flow (layered):**

1. `git clone --depth 1 --branch <commit>` from pinned source
2. **Layer 1 — Git commit signature:**
   - `git verify-commit <commit>` against trusted keys
   - Check signer fingerprint matches `signer` field in manifest
   - If untrusted → log warning, skip pack
3. **Layer 2 — Content hash:**
   - `find <path> -type f | sort | xargs sha256sum | sha256sum`
   - Compare against `integrity` field in manifest
   - If mismatch → log error, skip pack
4. If both pass → copy skills to `/workspace/.claude/skills/<pack-name>/`

**Failure mode:** Non-blocking. If verification fails, the pack is skipped
but the agent still starts. Errors are logged and surfaced via SSE events.

**Container spec:**
```yaml
initContainers:
  - name: skill-loader
    image: python:3.12-slim
    command: ["python3", "/scripts/skill_pack_loader.py"]
    env:
      - name: SKILL_PACKS_CONFIG
        value: /config/skill-packs.yaml
      - name: WORKSPACE_DIR
        value: /workspace
    volumeMounts:
      - name: workspace
        mountPath: /workspace
      - name: skill-config
        mountPath: /config
      - name: trusted-keys
        mountPath: /keys
```

### 3. Wizard — New "Skills" Step

Inserted between Source (Step 1) and Security (Step 3):

```
Step 1: Source
  [name, repo, variant]

Step 2: Skills          ← NEW
  ☑ superpowers (default)
  ☐ kagenti-ops
  ☐ custom...

  Pack source: github.com/anthropics/...
  Pinned commit: a1b2c3d (verified ✅)

Step 3: Security
  [isolation, landlock, proxy...]

Step 4: Identity
  ...
```

**UI behavior:**
- Reads `skill-packs.yaml` via backend API endpoint
- Shows available packs with checkboxes
- Packs with `default: true` are pre-checked
- Each pack shows: name, description, source URL, pinned commit (truncated),
  verification badge (✅ verified / ⚠️ unverified)
- Later: "Add custom pack" input for URL + commit hash

**Data flow:**
- Selected pack names are sent in the create-agent request body
- Backend adds init container config to the deployment manifest
- ConfigMap with `skill-packs.yaml` (filtered to selected packs) is mounted

### 4. Backend Changes

**New endpoint:** `GET /api/v1/sandbox/skill-packs`
- Returns parsed `skill-packs.yaml` for the wizard UI
- No auth required (pack metadata is not sensitive)

**Modified:** `POST /api/v1/sandbox/{namespace}/create`
- New field: `skill_packs: list[str]` (default: packs with `default: true`)
- Adds init container to deployment manifest
- Creates ConfigMap with selected packs config
- Mounts trusted keys as a Secret

### 5. E2E Test: Skill Invocation with Live CI Data

**File:** `kagenti/ui-v2/e2e/sandbox-skill-invocation.spec.ts`

```typescript
test('skill invocation with /tdd:ci loads skill and analyzes CI run', async ({ page }) => {
  // 1. Get 5 latest completed CI runs via GitHub API
  const runs = await getLatestCIRuns(5);  // gh run list --status completed -L 5

  // 2. Navigate to sandbox chat, select agent with skills
  await loginAndNavigateToSandbox(page);
  await selectAgent(page, 'sandbox-legion');

  // 3. For each CI run, send /tdd:ci #{run_id}
  for (const run of runs) {
    await sendMessage(page, `/tdd:ci #${run.databaseId}`);

    // 4. Wait for structured response
    await waitForAgentResponse(page, {
      timeout: 90_000,
      sections: ['Summary', 'Failures', 'Root Cause'],  // expected markdown sections
    });

    // 5. Verify agent made expected tool calls
    await expectToolCalls(page, ['web_fetch', 'shell']);  // CI log fetch + analysis
  }
});

test('superpowers skill pack is injected by default', async ({ page }) => {
  // Verify agent has superpowers skills loaded
  await loginAndNavigateToSandbox(page);
  await selectAgent(page, 'sandbox-legion');

  // Send a message that would trigger brainstorming skill
  await sendMessage(page, 'Help me design a new feature for user notifications');

  // Agent should reference brainstorming skill in its approach
  await waitForAgentResponse(page, {
    timeout: 90_000,
    contains: ['brainstorm', 'design', 'approach'],
  });
});
```

## Implementation Files

| File | Action | Owner |
|------|--------|-------|
| `skill-packs.yaml` | NEW — manifest in repo root | Session M |
| `deployments/sandbox/skill_pack_loader.py` | NEW — init container script | Session M |
| `deployments/sandbox/tests/test_skill_pack_loader.py` | NEW — unit tests | Session M |
| `kagenti/backend/app/routers/sandbox_deploy.py` | MODIFY — add init container | Session K (coordinate) |
| `kagenti/ui-v2/src/pages/SandboxCreatePage.tsx` | MODIFY — add Skills step | Session M |
| `kagenti/ui-v2/e2e/sandbox-skill-invocation.spec.ts` | NEW — E2E test | Session M |

## Migration Path

1. **Phase 1** (this PR): `skill-packs.yaml` + `skill_pack_loader.py` + unit tests
2. **Phase 2**: Wizard Skills step + backend API
3. **Phase 3**: E2E test with live CI data
4. **Phase 4**: Dynamic skill pack browser in wizard (custom URLs)

## Security Considerations

- **Supply chain:** Pinned commits + GPG signatures prevent MITM/substitution attacks
- **Content integrity:** SHA256 hash of skills directory catches post-clone tampering
- **Trusted keys:** Stored as K8s Secret, not baked into image
- **Non-blocking:** Failed verification skips the pack, doesn't crash the agent
- **Network:** Init container needs egress to GitHub — works with proxy sidecar
