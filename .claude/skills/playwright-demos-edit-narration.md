# Edit Narration and Re-Sync

Edit narration text and regenerate the synced video.

## Workflow

1. Edit `local_experiments/narrations/<test-name>.txt`
2. Run with `--sync` to regenerate timing and video
3. Check alignment table output
4. Iterate until narration matches video actions

## Narration File Location

```
local_experiments/narrations/walkthrough-demo.txt
```

## Section Format

```
[section_name]
Narration text. Must match a markStep('section_name') in the test.
Multiple sentences are fine. Keep each section focused on what's
visible on screen at that moment.

[next_section]
Next section text.
```

## Alignment Rules

1. **Each `markStep()` in the test must have a matching `[section]` in the narration**
2. **Narration should describe what's CURRENTLY visible**, not what's about to happen
3. **If narration > UI time**: sync adds extra wait (brief pause after actions)
4. **If narration < UI time**: silence fills the gap (may feel idle)
5. **If gap > narration + 5s**: consider adding more narration text

## Splitting Long Sections

If a section has a 30s narration but 70s of UI time:

**Before:**
```
[mlflow]
Long narration covering login, experiments, traces, and details...
```

**After:**
```
[mlflow]
Short intro about navigating to MLflow and logging in.

[mlflow_experiments]
Description of the experiments list view.

[mlflow_traces]
Description of the traces view with agent interactions.

[mlflow_detail]
Description of the trace detail view with span tree.
```

Then add matching `markStep()` calls in the test at each transition point.

## Pronunciation

OpenAI TTS doesn't support SSML. Use spelling tricks:

| Want | Write |
|------|-------|
| Kagenti (kay-JEN-tee) | Kay-jentee |
| A2A | A-to-A |
| mTLS | mutual TLS |
| OIDC | O-I-D-C |
| GenAI | Gen A-I |

## Iterative Alignment Process

After running `--sync`, check the voiceover alignment table in the output. For each section:

1. **Idle < 3s**: good — natural pause between narration and next action
2. **Idle 3-7s**: acceptable if page is loading (MLflow login, Kiali graph render)
3. **Idle > 7s**: add more narration text to fill the gap

### Filling Idle Gaps

Add contextual narration about what's happening on screen during loading:
- During MLflow login: explain OIDC integration, OpenTelemetry routing
- During experiment loading: describe experiment organization, GenAI categorization
- During Kiali graph: explain Istio Ambient mode, traffic patterns
- During Phoenix loading: compare with MLflow, explain real-time streaming

### Checking Alignment

The voiceover output shows `fits in X.Xs gap` for each section. Target:
```
[section] narration_duration fits in gap_duration gap
```
Where `gap - narration = 1-3s` (comfortable breathing room).

### Re-Running After Edits

```bash
source .env
./local_experiments/run-playwright-demo.sh --cluster-suffix <SUFFIX> --test walkthrough-demo --sync
```

The `--sync` flag does everything: fast run → measure timing → generate TTS → create synced test → slow run → composite voiceover. No dependency on previous runs.
