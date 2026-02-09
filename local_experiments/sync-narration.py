#!/usr/bin/env python3
"""
Sync narration timing with Playwright test.

Generates TTS audio for each narration section, measures durations,
and creates a _narration.spec.ts variant of the test with pauses
adjusted to match narration length.

Usage:
    python3 sync-narration.py --narration narrations/walkthrough-demo.txt \
        --test e2e/walkthrough-demo.spec.ts \
        --output e2e/walkthrough-demo_narration.spec.ts
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
RED = "\033[0;31m"
NC = "\033[0m"

BUFFER_MS = 1500  # Padding after narration


def info(msg):
    print(f"{CYAN}[sync]{NC} {msg}")


def warn(msg):
    print(f"{YELLOW}[sync]{NC} {msg}", file=sys.stderr)


def ok(msg):
    print(f"{GREEN}[sync]{NC} {msg}")


def get_audio_duration(path: str) -> float:
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
        )
        return float(r.stdout.strip()) if r.returncode == 0 else 0
    except Exception:
        return 0


def parse_sections(narration_path: str) -> list:
    text = Path(narration_path).read_text()
    sections = []
    current_section = None
    current_text = []

    for line in text.split("\n"):
        match = re.match(r"^\[(\w+)\]$", line.strip())
        if match:
            if current_section and current_text:
                sections.append((current_section, " ".join(current_text).strip()))
            current_section = match.group(1)
            current_text = []
        elif line.strip():
            current_text.append(line.strip())

    if current_section and current_text:
        sections.append((current_section, " ".join(current_text).strip()))

    return sections


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--narration", required=True)
    parser.add_argument("--test", required=True, help="Source test file")
    parser.add_argument("--output", required=True, help="Output _narration test file")
    parser.add_argument("--pauses-json", help="Also write pauses JSON for reference")
    parser.add_argument(
        "--timestamps", help="Pass 1 timestamps JSON (auto-detected if not set)"
    )
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        warn("OPENAI_API_KEY not set")
        return 1

    sections = parse_sections(args.narration)
    if not sections:
        warn(f"No sections found in {args.narration}")
        return 1

    info(f"Found {len(sections)} narration sections")

    tts_model = os.environ.get("TTS_MODEL", "tts-1-hd")
    tts_voice = os.environ.get("TTS_VOICE", "onyx")
    tts_speed = float(os.environ.get("TTS_SPEED", "1.0"))

    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    # Generate TTS and measure durations
    pauses = {}
    total_narration = 0

    print()
    print(f"  {'Section':<20} {'Narration':<12} {'Pause':<12} Text")
    print(f"  {'─' * 20} {'─' * 12} {'─' * 12} {'─' * 45}")

    for section_name, section_text in sections:
        try:
            response = client.audio.speech.create(
                model=tts_model,
                voice=tts_voice,
                speed=tts_speed,
                input=section_text,
            )
        except Exception as e:
            warn(f"  [{section_name}] TTS failed: {e}")
            pauses[section_name] = 3000
            continue

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(response.content)
            f.flush()
            duration = get_audio_duration(f.name)
            os.unlink(f.name)

        pause_ms = int(duration * 1000) + BUFFER_MS
        pauses[section_name] = pause_ms
        total_narration += duration

        preview = section_text[:45] + ("..." if len(section_text) > 45 else "")
        print(
            f"  {section_name:<20} {duration:>6.1f}s      {pause_ms:>6}ms    {preview}"
        )

    # Load Pass 1 timestamps to calculate UI interaction time per section
    ts_file = args.timestamps or str(
        Path(args.test).parent.parent / "walkthrough-timestamps.json"
    )
    ui_durations = {}  # How long each section takes in the UI (without extra waits)
    section_order = [name for name, _ in sections]
    if Path(ts_file).exists():
        ts_data = json.loads(Path(ts_file).read_text())
        ts_map = {e["step"]: e["time"] for e in ts_data}
        for i, name in enumerate(section_order):
            if name in ts_map:
                # Duration = time until next section starts
                next_name = section_order[i + 1] if i + 1 < len(section_order) else None
                if next_name and next_name in ts_map:
                    ui_durations[name] = ts_map[next_name] - ts_map[name]
                else:
                    ui_durations[name] = 5.0  # last section default
        info(f"Loaded Pass 1 timestamps from {ts_file}")
    else:
        warn(
            f"No timestamps file found at {ts_file}, using narration duration as pause"
        )

    # Calculate extra wait needed per section:
    # extra_wait = max(0, narration_duration + buffer - ui_duration)
    BUFFER_S = BUFFER_MS / 1000
    extra_waits = {}
    print()
    print(
        f"  {'Section':<20} {'Narration':<10} {'UI time':<10} {'Extra wait':<12} Text"
    )
    print(f"  {'─' * 20} {'─' * 10} {'─' * 10} {'─' * 12} {'─' * 40}")

    for section_name, section_text in sections:
        narr_dur = (
            pauses.get(section_name, 3000) / 1000 - BUFFER_S
        )  # raw narration (without buffer)
        ui_dur = ui_durations.get(section_name, 3.0)
        needed = narr_dur + BUFFER_S  # total time we need for narration
        extra = max(0, needed - ui_dur)
        extra_waits[section_name] = int(extra * 1000)

        status = "✓" if extra < 1 else f"+{extra:.1f}s"
        preview = section_text[:35] + ("..." if len(section_text) > 35 else "")
        print(
            f"  {section_name:<20} {narr_dur:>6.1f}s    {ui_dur:>6.1f}s    {extra:>6.1f}s {status:<5} {preview}"
        )
        total_narration  # already computed above

    total_extra = sum(extra_waits.values()) / 1000
    total_video = sum(ui_durations.values()) + total_extra
    print()
    info(f"Total narration: {total_narration:.1f}s")
    info(f"Total UI time (Pass 1): {sum(ui_durations.values()):.1f}s")
    info(f"Extra wait added: {total_extra:.1f}s")
    info(f"Estimated video (Pass 2): {total_video:.1f}s")
    print()

    # Read the source test file
    source = Path(args.test).read_text()

    # Insert extra wait after each markStep() — only if narration needs more time
    def replace_markstep(match):
        full_match = match.group(0)
        section = match.group(1)
        extra_ms = extra_waits.get(section, 0)
        if extra_ms > 0:
            dur = extra_ms / 1000
            return f"{full_match}\n    await page.waitForTimeout({extra_ms}); // narration sync: +{dur:.1f}s for [{section}]"
        return full_match

    modified = re.sub(
        r"markStep\('(\w+)'\);",
        replace_markstep,
        source,
    )

    # Update pauses dict for the JSON output
    pauses = extra_waits

    # Write the narration variant
    output_path = Path(args.output)
    output_path.write_text(modified)
    ok(f"Created {output_path}")

    # Also write pauses JSON for reference
    if args.pauses_json:
        Path(args.pauses_json).write_text(json.dumps(pauses, indent=2))
        ok(f"Pauses JSON: {args.pauses_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
