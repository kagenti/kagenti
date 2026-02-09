# Generate Video with Synced TTS Narration

Create a demo video with AI-generated voiceover that's synchronized to the on-screen actions.

## Usage

```bash
source .env  # Must have OPENAI_API_KEY
./local_experiments/run-playwright-demo.sh --cluster-suffix <SUFFIX> --test walkthrough-demo --sync
```

## How --sync Works (Two-Pass Pipeline)

### Pass 1: Fast Run
- Runs the source test (`e2e/walkthrough-demo.spec.ts`) at normal speed
- Records `markStep()` timestamps to `walkthrough-timestamps.json`
- This measures how long each UI section takes naturally

### Sync Step
- `sync-narration.py` reads the narration file (`narrations/walkthrough-demo.txt`)
- Generates TTS audio for each `[section]` via OpenAI API
- Measures each audio segment's duration with `ffprobe`
- Compares narration duration vs UI time from Pass 1
- Calculates extra wait needed: `max(0, narration_duration + 1.5s_buffer - UI_time)`
- Injects `waitForTimeout()` calls into a copy of the test
- Saves to `e2e-narration/walkthrough-demo.spec.ts`

### Pass 2: Narration-Synced Run
- Runs the modified test with extra pauses where narration needs more time
- Records video with timing that matches the narration
- Writes new timestamps to `walkthrough-timestamps.json`

### Voiceover Compositing
- `add-voiceover.py` generates TTS for each section (again, to get exact audio)
- Places each audio segment at its `markStep()` timestamp using FFmpeg `adelay`
- Checks for overlaps — truncates with fade-out if narration overflows into next section
- Pads with silence to match video length
- Composites with FFmpeg → `_voiceover.mp4`

## Narration File Format

```
[section_name]
Narration text for this section. Can be multiple sentences.

[next_section]
Text for the next section.
```

Section names must match `markStep('section_name')` calls in the test.

## Alignment Table

The sync step prints an alignment table:

```
Section              Narration  UI time    Extra wait
──────────────────── ────────── ────────── ────────────
intro                   5.8s       2.0s       5.3s +5.3s   ← needs pause
login                   6.8s      11.1s       0.0s ✓       ← UI already long enough
agent_catalog           8.9s       7.7s       2.7s +2.7s
mlflow                  6.6s      43.9s       0.0s ✓       ← plenty of room
```

## Output Files

```
walkthrough-demo-..._YYYY-MM-DD_HH-MM.webm              # Raw video
walkthrough-demo-..._YYYY-MM-DD_HH-MM_narration.mp3     # Standalone audio
walkthrough-demo-..._YYYY-MM-DD_HH-MM_voiceover.mp4     # Video + audio composited
```

## Voice Configuration

```bash
TTS_VOICE=shimmer TTS_SPEED=0.9 ./local_experiments/run-playwright-demo.sh ...
```

| Voice | Character |
|-------|-----------|
| onyx | Deep, authoritative (default) |
| alloy | Neutral, balanced |
| echo | Warm, conversational |
| fable | British, storytelling |
| nova | Energetic, friendly |
| shimmer | Clear, professional |

## Pronunciation Tips

OpenAI TTS has no SSML. Use spelling tricks:
- "Kay-jentee" for Kagenti (K + soft-G like GenZ + tee)
- Hyphens add pauses: "K-agenti" vs "Kagenti"
- Spell out acronyms: "A-to-A" instead of "A2A"

## Iterating on Narration

1. Edit `narrations/walkthrough-demo.txt`
2. Re-run with `--sync`
3. Check the alignment table
4. If a section has too much idle time, add more narration text
5. If narration overflows, shorten the text or split into sub-sections

## Adding Sub-Sections

To split a long section (e.g., mlflow was 30s narration):

1. Add `markStep('mlflow_experiments')` in the test at the right moment
2. Add `[mlflow_experiments]` section in the narration file
3. Re-run with `--sync` — the alignment table will show the new sections
