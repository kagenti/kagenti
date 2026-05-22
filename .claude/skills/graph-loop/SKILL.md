---
name: graph-loop
description: TDD iteration loop across 4 environments (local Kind, custom HyperShift, CI Kind, CI HyperShift) with test matrix tracking and log analysis
---

# OpenShell E2E Test Graph Loop

Iterate on OpenShell E2E tests across all 4 environments until the test matrix is green.
Track iterations, detect regressions, and report status tables.

## CRITICAL: Idempotency & Forward Progress

This skill is designed for `/loop` — it MUST be idempotent and always progress forward.

### Rules:
1. **Check state first.** Before running anything, read `$LOG_DIR/test-matrix-tracking.md`
   (or create it). Know which iteration you're on and what passed last time.
2. **Never re-run passing tests.** If a test category passed in the previous iteration
   and no code changed, skip re-running it — mark as PASS (carry forward).
3. **Only fix, never regress.** Before committing a fix, run targeted tests to verify
   the fix works AND doesn't break previously-passing tests. If a commit causes
   regression, revert it immediately.
4. **Track flaky tests.** If a test passes sometimes and fails sometimes (same code),
   mark it as FLAKY in the matrix. Document the flakiness pattern in the tracking file.
   Flaky tests need root-cause analysis, not retries.
5. **Forward-only iteration counter.** Each iteration number is monotonically increasing.
   Never reuse an iteration number. If you need to re-run, increment.
6. **Resume from where you left off.** If the loop was interrupted, read the tracking
   file and continue from the last incomplete iteration. Don't restart from scratch.
7. **Show the matrix.** Every iteration MUST end with the full matrix table printed
   to the user, showing all 4 environments and all categories.

## Two-Speed Loop

The graph loop has two modes — use the **quick debug loop** to fix individual
failures fast, then switch to the **full iteration** to verify everything.

### Quick Debug Loop (inner loop — seconds to minutes)

For fixing specific failing tests on a LIVE cluster. No full redeploy.

1. **Identify the failing test** from the matrix
2. **Redeploy only the affected component:**
   ```bash
   # LiteLLM config change:
   kubectl apply -f - <<EOF ... EOF && kubectl rollout restart deploy/litellm-model-proxy -n team1

   # Test code change (no redeploy needed — pytest reads from disk):
   # just edit and rerun

   # Agent manifest change:
   kubectl apply -f deployments/openshell/agents/<agent>.yaml -n team1

   # Gateway change:
   kubectl delete sts openshell-gateway -n openshell-system --wait=false
   kubectl apply -k deployments/openshell/
   ```
3. **Run ONLY the failing tests:**
   ```bash
   OPENSHELL_LLM_AVAILABLE=true uv run pytest \
     kagenti/tests/e2e/openshell/test_12_litellm_claude_sandbox.py \
     -v --tb=short -k "test_name_pattern" \
     > $LOG_DIR/quick-debug.log 2>&1; echo "EXIT:$?"
   ```
4. **Check result** — if it passes, run a slightly broader set to check regressions:
   ```bash
   OPENSHELL_LLM_AVAILABLE=true uv run pytest \
     kagenti/tests/e2e/openshell/test_12_litellm_claude_sandbox.py \
     kagenti/tests/e2e/openshell/test_07_skill_execution.py \
     -v --tb=short -k "claude or litellm or waypoint" \
     > $LOG_DIR/quick-regression.log 2>&1; echo "EXIT:$?"
   ```
5. **Commit the fix** only when both targeted AND regression tests pass
6. **Return to full iteration** to verify across all environments

### Full Iteration (outer loop — 15-40 minutes)

Runs the complete `openshell-full-test.sh` end-to-end. Use AFTER quick debug
fixes are committed. Produces the matrix row with all categories.

**The flow:**
```
Quick debug (fix A) → Quick debug (fix B) → Commit → Full iteration → Matrix update
     ↑                                                                      |
     └──────────── if regression detected ──────────────────────────────────┘
```

## Environments

| ID | Environment | How to run | Credentials |
|----|-------------|-----------|-------------|
| `kind` | Local Kind | `openshell-full-test.sh --skip-cluster-create --skip-cluster-destroy` | `.env.maas` |
| `hcp` | Custom HyperShift | Same script with `--platform ocp`, uses `KUBECONFIG=~/clusters/hcp/<cluster>/auth/kubeconfig` | `.env.kagenti-hypershift-custom` + `.env.maas` |
| `ci-kind` | CI Kind | `/run-e2e-openshell` comment on PR | `OPENAI_API_KEY` GH secret |
| `ci-hcp` | CI HyperShift | Same trigger, runs `e2e-openshell-hypershift.yaml` | `OPENAI_API_KEY` GH secret |

### CRITICAL: CI Kind has TWO triggers — always use issue_comment run

The `e2e-openshell-kind.yaml` workflow fires on **both** `pull_request` and `issue_comment`.
The `pull_request` run has **NO secrets** (fork PRs) so LLM tests skip (~79/0/65).
The `issue_comment` run (from `/run-e2e-openshell`) has full secrets (~114/0/30).

**Always analyze the `issue_comment`-triggered run**, not the `pull_request` one:
```bash
# Find the CORRECT CI Kind run (issue_comment with secrets, not pull_request without)
CORRECT_RUN=$(gh run list --workflow e2e-openshell-kind.yaml --limit 10 \
  --json event,conclusion,databaseId \
  -q '[.[] | select(.event=="issue_comment" and .conclusion=="success")][0].databaseId')
gh run view "$CORRECT_RUN" --log 2>&1 | grep -E "PASSED|FAILED|SKIPPED|=====.*passed"
```

The `pull_request` run is useful only for infra-only validation (no LLM). For agent
coverage (Claude Code, OpenCode, skills), the `issue_comment` run is authoritative.

## Agent Capability Matrix (MANDATORY)

**Every agent MUST be tested for the same baseline capabilities.**
The graph-loop matrix is organized as Capability × Agent × Model, not by
test file. If an agent is missing a capability test, that is a gap to fix —
not an expected skip.

### Priority agents (must pass ALL capabilities)

1. **Claude Code** (`openshell_claude`) — CLI sandbox
2. **OpenCode** (`openshell_opencode`) — CLI sandbox
3. **OpenClaw** (`nemoclaw_openclaw`) — NemoClaw gateway

### Baseline agent capabilities (rows in the matrix)

Every agent must have tests for each of these (19 capabilities, 4 tiers):

**Tier 1: Infrastructure (no LLM)**

| # | Capability | Test pattern | Validates |
|---|---|---|---|
| 1 | **Connectivity** | `test_connectivity__<agent>` | Agent responds to basic request |
| 2 | **Credential security** | `test_credential_security__<agent>` | No hardcoded secrets |
| 3 | **Sandbox lifecycle** | `test_sandbox_lifecycle__<agent>` | Create, list, delete sandbox |
| 4 | **Workspace** | `test_workspace__<agent>` | Data persists across pod restarts |
| 5 | **Resource limits** | `test_resource_limits__<agent>` | Respects CPU/memory budgets |

**Tier 2: Capabilities (requires LLM)**

| # | Capability | Test pattern | Validates |
|---|---|---|---|
| 6 | **Multiturn** | `test_multiturn__<agent>` | Stateful 3+ turn conversation |
| 7 | **Context isolation** | `test_context_isolation__<agent>` | Sessions don't leak |
| 8 | **Session resume** | `test_session_resume__<agent>` | Survives pod restart |
| 9 | **Cross-session memory** | `test_cross_session_memory__<agent>` | Remembers previous sessions |
| 10 | **Streaming** | `test_streaming__<agent>` | Real-time response delivery |
| 11 | **Tool calling** | `test_tool_calling__<agent>` | Invokes tools (function calling) |
| 12 | **MCP direct** | `test_mcp_direct__<agent>` | Calls MCP server directly |
| 13 | **MCP via gateway** | `test_mcp_gateway__<agent>` | Calls MCP through gateway proxy |
| 14 | **MCP discovery** | `test_mcp_discovery__<agent>` | Discovers available MCP servers |
| 15 | **Concurrent sessions** | `test_concurrent_sessions__<agent>` | Multiple users don't interfere |

**Tier 3: Skills (per-model parametrized)**

| # | Capability | Test pattern | Validates |
|---|---|---|---|
| 1 | **Skill: PR review** | `test_skill_pr_review__<agent>__<model>` | LLM reviews code |
| 2 | **Skill: RCA** | `test_skill_rca__<agent>__<model>` | LLM diagnoses failures |
| 3 | **Skill: Security** | `test_skill_security__<agent>__<model>` | LLM finds vulnerabilities |
| 4 | **Skill: GitHub PR** | `test_skill_github_pr__<agent>__<model>` | Clones and reviews live PR |

**Tier 4: Security & Policy**

| # | Capability | Test pattern | Validates |
|---|---|---|---|
| 1 | **HITL: Network** | `test_hitl_network__<agent>` | Unauthorized egress blocked |
| 2 | **HITL: Tool approval** | `test_hitl_tool_approval__<agent>` | Requires permission before tool use |
| 3 | **HITL: MCP approval** | `test_hitl_mcp__<agent>` | MCP server requires approval before executing |
| 4 | **Audit logging** | `test_audit_logging__<agent>` | Actions produce OTel spans |

MISS = test doesn't exist yet (gap to file as issue).
SKIP with clear reason = acceptable temporarily.
SKIP without reason = failure.

Design spec: `docs/superpowers/specs/2026-05-02-agent-capability-test-matrix-design.md`

### Per-model parametrization (REQUIRED for skill tests)

All skill tests (PR review, RCA, security review, real GitHub PR) MUST be
parametrized across the configured LLM models. The matrix shows results
per model so we catch model-specific regressions.

Current models:
- `llama-scout-17b` (primary, via LiteMaaS)
- `deepseek-r1` (deepseek-r1-distill-qwen-14b, via LiteMaaS)
- `mistral-small` (mistral-small-24b, via LiteMaaS)

The test fixture receives the model name and passes it to the LLM call.
LiteLLM proxy routes to the correct backend. Test names look like:
`test_pr_review__openshell_claude__llama_scout_17b`
`test_pr_review__openshell_claude__deepseek_r1`

### MANDATORY Status Summary (print after EVERY iteration)

Every iteration MUST end with these 7 tables. Use `—` for environments not run.

1. **Environment Totals** — Pass/Fail/Skip/Total/Time per environment (4 rows)
2. **Capability × Agent** — P/F/S/FL per cell, 4 env values: CI/CH/LK/HCP
3. **Per-Model Stats** — tokens, time, quality per model (only if llm-metrics.json exists)
4. **Iteration Progress** — trend arrows comparing last 4 iterations
5. **Agent Summaries** — one-line verdict per agent
6. **Model Summaries** — one-line verdict per model
7. **Failure RCA** — every FAIL gets root cause + fix status

Legend: P=pass, F=fail, S=skip, —=miss, FL=flaky, CI=CI Kind, CH=CI HyperShift, LK=Local Kind, HCP=Custom HCP

## One Iteration

### Step 1: Run tests

Run on each available environment. Use background tasks for independence.

**Local Kind** (requires running Kind cluster with agents deployed):
```bash
export LOG_DIR=/tmp/kagenti/tdd-iter<N> && mkdir -p $LOG_DIR
.github/scripts/local-setup/openshell-full-test.sh \
  --skip-cluster-create --skip-cluster-destroy \
  > $LOG_DIR/kind-fulltest.log 2>&1; echo "EXIT:$?"
```

**Custom HyperShift** (requires ospoc or similar cluster):
```bash
cd /path/to/main/repo  # NOT worktree — credentials live here
source .env.kagenti-hypershift-custom
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-ospoc/auth/kubeconfig
/path/to/worktree/.github/scripts/local-setup/openshell-full-test.sh \
  --platform ocp --skip-cluster-create --skip-cluster-destroy \
  > $LOG_DIR/hcp-fulltest.log 2>&1; echo "EXIT:$?"
```

**CI** (push + comment):
```bash
git push
gh pr comment <PR> --body "/run-e2e-openshell"
# Wait for completion, then find the CORRECT run:
# IMPORTANT: CI Kind has two triggers. The pull_request run has NO secrets
# (LLM tests skip). Always use the issue_comment run for full coverage.
CI_KIND_RUN=$(gh run list --workflow e2e-openshell-kind.yaml --limit 10 \
  --json event,conclusion,databaseId \
  -q '[.[] | select(.event=="issue_comment" and .conclusion=="success")][0].databaseId')
gh run view "$CI_KIND_RUN" --log 2>&1 | grep -E "PASSED|FAILED|SKIPPED|=====.*passed" > $LOG_DIR/ci-kind-results.log

CI_HCP_RUN=$(gh run list --workflow e2e-openshell-hypershift.yaml --limit 5 \
  --json event,conclusion,databaseId \
  -q '[.[] | select(.conclusion=="success")][0].databaseId')
gh run view "$CI_HCP_RUN" --log 2>&1 | grep -E "PASSED|FAILED|SKIPPED|=====.*passed" > $LOG_DIR/ci-hcp-results.log
```

### Step 2: Analyze results

Use a subagent per log file:
```
Agent(subagent_type='Explore'):
  "Read $LOG_DIR/<env>-fulltest.log. Report:
   1. Final pytest summary (passed/failed/skipped)
   2. ALL FAILED test names
   3. ALL tests matching: claude|opencode|adk|litellm|waypoint|gateway
   Use grep -E, do NOT read full file. Under 200 words."
```

### Step 3: Build the matrix

Fill in the iteration row in the tracking file. Mark each category:
- **PASS** — all tests in category pass
- **FAIL(N)** — N tests fail (list which)
- **SKIP** — all tests skip (note why)
- **BLOCK** — environment unreachable or deploy failed

### Step 4: Compare to previous iteration

Check if we improved:
- New PASSes? → good
- New FAILs? → regression, investigate immediately
- Same FAILs? → root-cause and fix
- More SKIPs? → check env/credential issues

### Step 5: Fix and commit

Fix the root cause of failures. Commit with descriptive message.
Do NOT commit if tests regressed from previous iteration.

## Tracking File

Maintain at `/tmp/kagenti/test-matrix-tracking.md` (or `docs/plans/` for persistence).

Format:
```markdown
# OpenShell E2E Test Matrix

## Iteration N — YYYY-MM-DD HH:MM
Commits: `<short-sha> <message>`

| Category | Local Kind | Custom HCP | CI Kind | CI HCP |
|----------|-----------|-----------|---------|--------|
| Waypoint | PASS | PASS | PASS | PASS |
| LiteLLM secure | PASS | SKIP | SKIP | SKIP |
| Anthropic passthrough | PASS | PASS | SKIP | SKIP |
| Claude Code sandbox | PASS | PASS | PASS | PASS |
| Claude Code skills | PASS(3/4) | SKIP | SKIP | SKIP |
| OpenCode sandbox | PASS | SKIP | SKIP | SKIP |
| ADK agent | PASS | PASS | PASS | SKIP |
| Claude SDK agent | PASS | PASS | PASS | PASS |
| Gateway | PASS | PASS | PASS | FAIL(5) |
| Platform | PASS | PASS | PASS | PASS |
| **Total** | **X/Y/Z** | **X/Y/Z** | **X/Y/Z** | **X/Y/Z** |

Changes from previous iteration:
- [+] Claude Code sandbox: SKIP → PASS (shared pod fix)
- [-] Gateway: PASS → FAIL (image pull issue on HCP)
```

## Why tests skip in CI

Common causes and fixes:

| Symptom | Cause | Fix |
|---------|-------|-----|
| All LLM tests skip | `OPENSHELL_LLM_AVAILABLE` not set | Script doesn't detect `OPENAI_API_KEY` from GH secrets — need `.env.maas` file fallback |
| Sandbox tests skip | `sandbox_crd_installed()` returns False | CRD not applied before pytest collection |
| OpenCode/Claude skip | `run_*_in_sandbox()` returns None | Sandbox pod failed to start — check image pull, namespace, secrets |
| ADK skip on HCP | Port-forward fails | Supervisor netns blocks — use port-bridge sidecar |
| Gateway tests fail on HCP | Gateway pod not running | Image pull auth, SCC, or StatefulSet immutable field |

## Loop Model

Run **at least 5 iterations** before giving up on aligning the matrix.
Each iteration runs environments in parallel at their natural speed:
- **Fast lane**: Local Kind + CI Kind (push triggers CI, run local simultaneously)
- **Slow lane**: Custom HyperShift (deploy takes longer, run after local Kind validates)
- **Passive**: CI HyperShift (triggered by same `/run-e2e-openshell` comment)

### Iteration workflow:
1. **Fix** — apply fixes from previous iteration's failures
2. **Commit + push** — triggers CI Kind + CI HyperShift
3. **Run local Kind** — background, parallel with CI
4. **Run custom HyperShift** — background if cluster ready, otherwise after Kind
5. **Collect results** — use subagents to parse all logs in parallel
6. **Update matrix** — fill in iteration row, compare to previous
7. **Brainstorm** — if same failures persist across iterations, use
   `superpowers:brainstorming` or `superpowers:systematic-debugging` to
   rethink the approach before the next iteration

### After 5 iterations:
- Show final matrix table grouped by test category
- Highlight: what passes everywhere, what's environment-specific, what's flaky
- Brainstorm with user on misaligned columns

## Event Graph Validation

The "graph" in graph-loop means reconstructing the flow of events across
components and validating the expected sequence occurred. This goes beyond
pass/fail — it verifies the ARCHITECTURE is working correctly.

### How it works:
1. **Collect logs** from all components after a test run
2. **Reconstruct the event graph** — trace a request through the system:
   ```
   Claude Code → ANTHROPIC_BASE_URL → LiteLLM /v1/messages
     → hosted_vllm translation → LiteMaaS /v1/chat/completions
     → response back through LiteLLM → Anthropic format → Claude Code
   ```
3. **Assert expected events present** in the logs:
   - LiteLLM: `POST /v1/messages` received, model resolved, upstream call made
   - Gateway: sandbox created, pod scheduled, exec completed
   - Waypoint: HBONE connection established, no cert errors
4. **Flag missing events** — if a step is missing, the architecture has a gap

### Log levels:
- **INFO** (default): sufficient for most validation — request/response logging
- **DEBUG**: enable per-component when investigating specific failures:
  ```bash
  kubectl set env deploy/litellm-model-proxy -n team1 LITELLM_LOG=DEBUG
  kubectl set env deploy/claude-sdk-agent -n team1 -c agent LOG_LEVEL=DEBUG
  ```
- Only enable DEBUG for the component under investigation, reset after

### Example event graph assertion (for Claude Code sandbox test):
```
[litellm] INFO POST /v1/messages model=claude-sonnet-4-20250514
[litellm] INFO Using chat_completions path (anthropic messages translation)
[litellm] INFO Upstream call to hosted_vllm/llama-scout-17b
[litellm] INFO Response 200 tokens=N
```
If any line is missing → the test should flag it even if the response was correct.

## Log Analysis (per iteration)

Every iteration must also analyze component logs for errors and warnings.
Target: **0 errors, minimum warnings**.

### Collect logs (after test run, before cleanup):
```bash
for COMP in openshell-gateway litellm-model-proxy; do
  kubectl logs deploy/$COMP -n ${NS:-team1} --tail=500 > $LOG_DIR/${COMP}.log 2>&1 || true
done
for COMP in claude-sdk-agent adk-agent-supervised weather-agent-supervised; do
  kubectl logs deploy/$COMP -n team1 -c agent --tail=200 > $LOG_DIR/${COMP}.log 2>&1 || true
done
kubectl logs -n istio-system -l app=ztunnel --tail=100 > $LOG_DIR/ztunnel.log 2>&1 || true
kubectl logs deploy/waypoint -n team1 --tail=100 > $LOG_DIR/waypoint.log 2>&1 || true
```

### Analyze with subagent:
```
Agent(subagent_type='Explore'):
  "Grep $LOG_DIR/*.log for ERROR|WARN|error|warn|panic|fatal.
   Categorize by component and severity.
   Exclude known noise: 'deprecated', 'liveness probe'.
   Report: component, count of errors, count of warnings, sample messages.
   Under 200 words."
```

### Log matrix columns:
| Component | Errors | Warnings | Notes |
|-----------|--------|----------|-------|
| openshell-gateway | 0 | 2 | deprecation warnings (known) |
| litellm-model-proxy | 0 | 0 | clean |
| claude-sdk-agent | 0 | 1 | reconnect warning |
| ztunnel | 0 | 0 | clean |
| waypoint | 0 | 0 | clean |

### OTel structured logging
Verify agents emit structured JSON logs with OTel fields:
- `trace_id`, `span_id` in log entries (when tracing enabled)
- `level`, `msg`, `component` fields
- No raw print() or unstructured output in production paths

## Done condition

All 4 environments show:
- Claude Code sandbox: PASS
- OpenCode sandbox: PASS
- ADK agent: PASS
- Gateway: PASS
- 0 FAIL, only expected SKIP (e.g., NemoClaw when not deployed)
- 0 ERROR in component logs
- Warnings catalogued and either fixed or documented as known

## End-of-Cycle Review (after 5 iterations)

After 5 iterations or when progress stalls, present: final matrix, resolved
items, remaining blockers with options, and batched questions for user to
unblock the next cycle. User answers all at once → clear direction.
