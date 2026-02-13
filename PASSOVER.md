# Passover: Playwright Demo Videos

## What's Done

- 21 Playwright demo test specs with section assertions in `local_experiments/e2e/`
- 21 narration files in `local_experiments/narrations/`
- Nested demos/ directory structure with `demo-map.json`
- `sync-narration.py` fixed with cumulative timing gates (guarantees no audio overlap)
- `add-voiceover.py` fixed to use per-test timestamps + audio_segments/ caching
- `run-playwright-demo.sh` updated for per-test output dirs (parallel-safe)
- `run-demo-quiet.sh` wrapper that logs to files (avoids Claude Code OOM)
- `sync-to-gdrive.sh` for Google Drive upload
- Skills: `test:playwright`, `playwright-demo`, `playwright-research` all updated
- Branches pushed: `playwright-demos`, `ai-ops-skills-v2`

## What Needs Re-Recording

6 demos were recorded with the OLD sync algorithm (before timing gate fix).
Re-record on ladas1 cluster:

```bash
cd .worktrees/playwright-demos
source .env
for test in agent-build agent-import mcp-gateway tool-import tool-integration agent-delete; do
  echo "=== $test ==="
  ./local_experiments/run-demo-quiet.sh --cluster-suffix ladas1 --test $test
  echo "EXIT: $?"
done
```

Check logs in `local_experiments/logs/`.

## What's Missing

1. `01-demos/full-platform-walkthrough` — needs walkthrough-demo re-run:
   ```bash
   ./local_experiments/run-demo-quiet.sh --cluster-suffix ladas1 --test walkthrough-demo
   ```

2. `e2e-deploy` test fails on ladas1 due to `ClusterBuildStrategyNotFound`
   — needs `buildah-insecure-push` ClusterBuildStrategy deployed, or change
   the test to use a pre-built image instead of source build.

## Key Files

| File | Purpose |
|------|---------|
| `local_experiments/run-demo-quiet.sh` | Run one test, log to file, print summary only |
| `local_experiments/run-playwright-demo.sh` | Full pipeline (3-step with TTS) |
| `local_experiments/sync-narration.py` | Timing gate injection (cumulative targets) |
| `local_experiments/add-voiceover.py` | TTS generation + FFmpeg compositing |
| `local_experiments/demo-map.json` | Test name → nested output dir mapping |
| `local_experiments/validate-alignment.py` | Check narration-video alignment |
| `TODO_VIDEOS.md` | Master plan for all demos |

## Cluster

Using `ladas1` (suffix). Kubeconfig at:
```
~/clusters/hcp/kagenti-hypershift-custom-ladas1/auth/kubeconfig
```

Has: weather-service, weather-tool in team1. MLflow, Phoenix, Kiali, Keycloak, MCP Inspector all deployed.

## Running from Claude Code

The conversation context causes Node.js OOM after extended sessions.
To avoid this, run demos with exit-code-only output:

```bash
cd .worktrees/playwright-demos && source .env
./local_experiments/run-demo-quiet.sh --cluster-suffix ladas1 --test <name> > /dev/null 2>&1; echo $?
```

Or use subagents (one per demo) to isolate memory.

## Git Status

```
playwright-demos branch: 33446cfd (per-test output dirs)
ai-ops-skills-v2 branch: d2afe86e (test:playwright skill)
```

Both pushed to origin. Need rebase onto upstream/main if upstream moved.

## Validation

After re-recording, run validation on all:
```bash
cd local_experiments
for narr in narrations/*.txt; do
  name=$(basename "$narr" .txt)
  ts=$(find demos -name "${name}-timestamps.json" | head -1)
  [ -n "$ts" ] && python3 validate-alignment.py --timestamps "$ts" --narration "$narr" 2>/dev/null | grep Coverage
done
```

Target: all demos show "fits in" for every segment in voiceover output.
