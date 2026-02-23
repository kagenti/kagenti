# Align Narration with Video

Ensure narration matches on-screen actions with no dead air or mismatched descriptions.

## Principle

Every second of video should either have:
1. **Narration playing** — describing what's visible on screen
2. **Brief natural pause** (1-3s) — between narration sections while the next action starts
3. **NEVER** more than 7s of silence while the screen shows static content

## Alignment Workflow

### 1. Run `--sync` and check alignment table

```bash
source .env
./local_experiments/run-playwright-demo.sh --cluster-suffix <SUFFIX> --test walkthrough-demo --sync
```

Look for the `fits in` output:
```
[intro] 6.0s fits in 7.9s gap        ← 1.9s idle ✓
[mlflow] 36.9s fits in 44.1s gap     ← 7.2s idle ⚠
```

### 2. Identify problem sections

| Idle Time | Action |
|-----------|--------|
| < 1.3s | Target — tight natural pause |
| 1.3-3s | Acceptable — add one more sentence if possible |
| 3-5s | Must fix — add contextual narration about what's loading |
| > 5s | Split into sub-sections with `markStep()` and add narration |

**Target: max 1.3s idle per section.** If UI loading takes longer than narration, add more narration text explaining the architecture, security, or integration details relevant to what's on screen. Never leave the viewer watching a static screen in silence.

### 3. Fix misaligned narration

If narration describes actions that haven't happened yet:
- The `markStep()` is placed too early in the test
- Move `markStep()` to RIGHT BEFORE the action the narration describes

If narration finishes long before the next section:
- Add more contextual narration about what's loading/happening
- Good fillers: explain architecture, security, integration details

### 4. Split large sections

A section with > 15s UI time should be split:

**Test:** Add `markStep('mlflow_experiments')` at the transition point
**Narration:** Add `[mlflow_experiments]` with matching text

### 5. Validate narration content matches video

For each section, verify:
- Narration starts when the described UI element becomes visible
- Narration doesn't reference elements that appear later
- Transition words ("Next", "Now", "Finally") match the visual flow

## Section Naming Convention

```
<app>                  → initial navigation/login
<app>_<feature>        → specific feature within the app
<app>_<feature>_detail → drill-down into details
```

Examples:
```
mlflow → mlflow_experiments → mlflow_traces → mlflow_detail
kiali → kiali_graph → kiali_security
phoenix → phoenix_traces
```

## Estimating Narration Duration

Approximate: **14-16 characters per second** for OpenAI TTS at speed 1.0.

```
100 chars ≈ 6-7 seconds
200 chars ≈ 12-14 seconds
500 chars ≈ 30-35 seconds
```

Use this to estimate if added text will fill a gap before re-running.
