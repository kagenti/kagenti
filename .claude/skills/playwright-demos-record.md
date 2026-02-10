# Record a Playwright Demo Video

Record a walkthrough video of the Kagenti platform. Automatically adds narration if OPENAI_API_KEY is set.

## Usage

```bash
# Video only (no narration)
./local_experiments/run-playwright-demo.sh --cluster-suffix <SUFFIX> --test walkthrough-demo

# Video + narration (automatic when OPENAI_API_KEY is set)
source .env  # has OPENAI_API_KEY
./local_experiments/run-playwright-demo.sh --cluster-suffix <SUFFIX> --test walkthrough-demo
```

## What Happens

### Without OPENAI_API_KEY
Records a single fast video and saves to `demos/<testname>/`.

### With OPENAI_API_KEY (3-step pipeline)

```
Step 1: Fast run → measure video slot timing per section
        ↓
Step 2: Generate TTS for each narration section → measure audio durations
        Compare narration vs video slots:
        - If narration < slot: validation says "add N chars to section X"
          → LLM expands narration text → re-run
        - If narration > slot: sync adds extra wait to video
        ↓
Step 3: Record narration-synced video → composite voiceover → validate
```

### Output

```
demos/<testname>/
├── walkthrough-demo-..._YYYY-MM-DD_HH-MM.webm              # Raw video
├── walkthrough-demo-..._YYYY-MM-DD_HH-MM_narration.mp3     # Standalone audio
└── walkthrough-demo-..._YYYY-MM-DD_HH-MM_voiceover.mp4     # Video + narration
```

## Validation

Runs automatically after each recording. If it shows idle gaps:

1. Read the action plan (which sections need more narration text)
2. Edit `local_experiments/narrations/<testname>.txt`
3. Re-run the script — converges in 2 iterations max

## Voice Options

```bash
TTS_VOICE=shimmer TTS_SPEED=0.9 ./local_experiments/run-playwright-demo.sh ...
```

Voices: onyx (default), alloy, echo, fable, nova, shimmer
