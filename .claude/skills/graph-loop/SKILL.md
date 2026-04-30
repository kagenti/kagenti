---
name: graph-loop
description: TDD iteration loop across 4 environments (local Kind, custom HyperShift, CI Kind, CI HyperShift) with test matrix tracking and log analysis
---

# OpenShell E2E Test Graph Loop

Iterate on OpenShell E2E tests across all 4 environments until the test matrix is green.
Track iterations, detect regressions, and report status tables.

## Environments

| ID | Environment | How to run | Credentials |
|----|-------------|-----------|-------------|
| `kind` | Local Kind | `openshell-full-test.sh --skip-cluster-create --skip-cluster-destroy` | `.env.maas` |
| `hcp` | Custom HyperShift | Same script with `--platform ocp`, uses `KUBECONFIG=~/clusters/hcp/<cluster>/auth/kubeconfig` | `.env.kagenti-hypershift-custom` + `.env.maas` |
| `ci-kind` | CI Kind | Push + `/run-e2e-openshell` comment on PR | `OPENAI_API_KEY` GH secret |
| `ci-hcp` | CI HyperShift | Same trigger, runs `e2e-openshell-hypershift.yaml` | `OPENAI_API_KEY` GH secret |

## Test Categories (columns in matrix)

| Category | Key tests | Pass condition |
|----------|-----------|----------------|
| **Waypoint** | `test_waypoint_exists_if_labeled[team1,team2]`, `test_waypoint_pod_running` | All PASS |
| **LiteLLM secure** | `test_configmap_no_plaintext_api_keys`, `test_litemaas_secret_exists`, `test_litellm_deployment_uses_secret_ref`, `test_litellm_uses_hosted_vllm_provider`, `test_litellm_anthropic_settings` | All PASS (skip OK if no LLM) |
| **Anthropic passthrough** | `test_anthropic_messages_api_returns_response`, `test_claude_model_alias_in_model_list` | All PASS |
| **Claude Code sandbox** | `test_claude_code_simple_prompt`, `test_claude_code_code_review` | All PASS |
| **Claude Code skills** | `test_pr_review__openshell_claude`, `test_rca__openshell_claude`, `test_security_review__openshell_claude`, `test_real_github_pr__openshell_claude` | All PASS |
| **OpenCode sandbox** | `test_pr_review__openshell_opencode`, `test_rca__openshell_opencode`, `test_security_review__openshell_opencode` | All PASS |
| **ADK agent** | `test_hello__adk_supervised`, `test_pr_review__adk_agent`, `test_rca__adk_agent` | All PASS |
| **Claude SDK agent** | `test_hello__claude_sdk_agent`, `test_pr_review__claude_sdk_agent`, `test_rca__claude_sdk_agent` | All PASS |
| **Gateway** | `test_gateway_pod_running`, `test_gateway_containers_ready`, `test_gateway_processes_sandbox` | All PASS |
| **Platform** | `test_operator_pod_running`, all test_01 | All PASS |

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
# Wait for completion, then:
gh run view <run-id> --log 2>&1 | grep -E "PASSED|FAILED|SKIPPED|=====.*passed" > $LOG_DIR/ci-results.log
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
