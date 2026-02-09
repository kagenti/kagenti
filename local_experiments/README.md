# Local Experiments

This directory is gitignored and contains local development/experimentation scripts.

## Playwright Demo Recorder

Records video of Playwright E2E tests running against a live Kagenti cluster with
Keycloak authentication.

### Quick Start

```bash
# See available tests (dry run)
./local_experiments/run-playwright-demo.sh --cluster-suffix ladas

# Record a specific test
./local_experiments/run-playwright-demo.sh --cluster-suffix ladas --test home

# Record all tests
./local_experiments/run-playwright-demo.sh --cluster-suffix ladas --all

# Kind cluster
./local_experiments/run-playwright-demo.sh --kind --test home

# From a worktree
./local_experiments/run-playwright-demo.sh --cluster-suffix ladas \
    --repo-path .worktrees/my-feature --test agent
```

### Voiceover (optional)

Set `OPENAI_API_KEY` to automatically generate voiceover for recorded videos:

```bash
export OPENAI_API_KEY=sk-...
./local_experiments/run-playwright-demo.sh --cluster-suffix ladas --all
```

Requires: `pip install openai` and `ffmpeg` in PATH.

Custom narration scripts go in `narrations/<test-name>.txt`.

### Output

```
local_experiments/
  home_2026-02-08_14-30.webm                    # Raw recording
  home_2026-02-08_14-30_voiceover.mp4            # With voiceover (if OPENAI_API_KEY set)
  agent-catalog_2026-02-08_14-30.webm
  agent-catalog_2026-02-08_14-30_voiceover.mp4
```
