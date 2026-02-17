# Playwright Demo Video Recording

Record, narrate, and manage demo videos of the Kagenti platform using Playwright browser automation.

## Sub-skills

- `playwright-demos:record` — Record a walkthrough video (fast, no narration)
- `playwright-demos:narrate` — Generate video with synced TTS narration
- `playwright-demos:create-test` — Create a new walkthrough test spec
- `playwright-demos:edit-narration` — Edit narration text and re-sync timing
- `playwright-demos:debug` — Debug failing Playwright steps

## Directory Structure

```
local_experiments/
├── run-playwright-demo.sh       # Main entry script
├── add-voiceover.py             # TTS generation + FFmpeg compositing
├── sync-narration.py            # Narration timing sync (generates _narration tests)
├── keycloak-auth-setup.ts       # Playwright global auth setup
├── e2e/                         # Source walkthrough tests (fast, no narration pauses)
│   └── walkthrough-demo.spec.ts
├── e2e-narration/               # Generated narration-synced tests (gitignored)
├── narrations/                  # Narration text files with [section] markers
│   └── walkthrough-demo.txt
├── test-results/                # Playwright output (gitignored)
├── .auth/                       # Saved Keycloak auth state (gitignored)
├── section-pauses.json          # Generated pause calculations
└── walkthrough-timestamps.json  # Step timestamps from last run
```

## Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Required for TTS narration |
| `TTS_VOICE` | OpenAI voice: onyx, alloy, echo, fable, nova, shimmer |
| `TTS_SPEED` | Speech speed: 0.25 to 4.0 (default: 1.0) |
| `TTS_MODEL` | TTS model: tts-1 or tts-1-hd (default: tts-1-hd) |
| `KEYCLOAK_USER` / `KEYCLOAK_PASS` | Override auto-discovered credentials |
| `KUBEADMIN_PASS` | For Kiali OpenShift OAuth login |

## Prerequisites

- HyperShift or Kind cluster with Kagenti deployed
- Node.js with Playwright (`npm install` in `kagenti/ui-v2/`)
- `uv` (Python package manager)
- `ffmpeg` and `ffprobe` for video compositing
- OpenAI API key for TTS narration (optional for video-only recording)
