#!/usr/bin/env python3
"""
Validate narration-to-video alignment.

Checks:
1. All narration sections have matching timestamps (no missing markStep)
2. All timestamps have matching narration sections (no orphaned steps)
3. No section gap exceeds MAX_IDLE (1.3s default)
4. No audio segments overlap
5. Audio segment fits within its video slot
6. Reports per-section breakdown with pass/fail

Run after ANY change to narration text, test timing, or section structure.

Usage:
    python3 validate-alignment.py
    python3 validate-alignment.py --timestamps walkthrough-timestamps.json --narration narrations/walkthrough-demo.txt
    python3 validate-alignment.py --audio-dir audio_segments/  # validate cached audio segments
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
NC = "\033[0m"
BOLD = "\033[1m"

MAX_IDLE_S = 1.3  # Maximum allowed silence between narration end and next section


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


def parse_narration_sections(path: str) -> list:
    text = Path(path).read_text()
    sections = []
    current = None
    current_text = []
    for line in text.split("\n"):
        m = re.match(r"^\[(\w+)\]$", line.strip())
        if m:
            if current and current_text:
                sections.append((current, " ".join(current_text).strip()))
            current = m.group(1)
            current_text = []
        elif line.strip():
            current_text.append(line.strip())
    if current and current_text:
        sections.append((current, " ".join(current_text).strip()))
    return sections


def estimate_tts_duration(text: str, speed: float = 1.0) -> float:
    """Estimate TTS duration: ~14-16 chars/second at speed 1.0."""
    chars = len(text)
    return (chars / 15.0) / speed


def main():
    parser = argparse.ArgumentParser(description="Validate narration-video alignment")
    parser.add_argument("--timestamps", default=None, help="Timestamps JSON file")
    parser.add_argument("--narration", default=None, help="Narration text file")
    parser.add_argument(
        "--audio-dir", default=None, help="Directory with cached audio segments"
    )
    parser.add_argument(
        "--max-idle",
        type=float,
        default=MAX_IDLE_S,
        help=f"Max idle seconds (default: {MAX_IDLE_S})",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    ts_file = (
        Path(args.timestamps)
        if args.timestamps
        else script_dir / "walkthrough-timestamps.json"
    )
    narr_file = (
        Path(args.narration)
        if args.narration
        else script_dir / "narrations" / "walkthrough-demo.txt"
    )
    audio_dir = (
        Path(args.audio_dir) if args.audio_dir else script_dir / "audio_segments"
    )

    errors = []
    warnings = []

    print()
    print(f"{BOLD}{'=' * 80}{NC}")
    print(f"{BOLD}  Narration-Video Alignment Validation{NC}")
    print(f"{BOLD}{'=' * 80}{NC}")
    print()

    # ── Load data ──────────────────────────────────────────────────────
    if not narr_file.exists():
        print(f"{RED}FAIL{NC} Narration file not found: {narr_file}")
        return 1
    sections = parse_narration_sections(str(narr_file))
    section_names = [name for name, _ in sections]
    section_texts = {name: text for name, text in sections}
    print(f"{CYAN}Narration:{NC} {narr_file} ({len(sections)} sections)")

    timestamps = {}
    if ts_file.exists():
        ts_data = json.loads(ts_file.read_text())
        timestamps = {e["step"]: e["time"] for e in ts_data}
        print(f"{CYAN}Timestamps:{NC} {ts_file} ({len(timestamps)} steps)")
    else:
        print(f"{YELLOW}WARN{NC} No timestamps file — using estimates only")

    # Get audio durations (from cached segments or estimates)
    audio_durations = {}
    for name, text in sections:
        seg_file = audio_dir / f"{name}.mp3"
        if seg_file.exists():
            audio_durations[name] = get_audio_duration(str(seg_file))
        else:
            audio_durations[name] = estimate_tts_duration(text)

    has_cached_audio = any((audio_dir / f"{name}.mp3").exists() for name, _ in sections)
    dur_source = "cached audio" if has_cached_audio else "estimated (~15 chars/s)"
    print(f"{CYAN}Audio durations:{NC} {dur_source}")
    print()

    # ── Check 1: Section ↔ Timestamp matching ──────────────────────────
    print(f"{BOLD}Check 1: Section ↔ Timestamp Matching{NC}")

    missing_timestamps = [
        name
        for name in section_names
        if name in section_names and name not in timestamps and timestamps
    ]
    orphaned_timestamps = [name for name in timestamps if name not in section_names]

    if missing_timestamps:
        for name in missing_timestamps:
            msg = f"Section [{name}] has no markStep() timestamp"
            errors.append(msg)
            print(f"  {RED}FAIL{NC} {msg}")
    if orphaned_timestamps:
        for name in orphaned_timestamps:
            msg = f"Timestamp '{name}' has no narration section"
            warnings.append(msg)
            print(f"  {YELLOW}WARN{NC} {msg}")
    if not missing_timestamps and not orphaned_timestamps:
        print(
            f"  {GREEN}PASS{NC} All {len(sections)} sections have matching timestamps"
        )
    print()

    # ── Check 2: Per-section alignment ─────────────────────────────────
    print(f"{BOLD}Check 2: Per-Section Alignment (max idle: {args.max_idle}s){NC}")
    print()
    print(f"  {'Section':<25} {'Audio':<8} {'Slot':<8} {'Idle':<8} {'Status'}")
    print(f"  {'─' * 25} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 20}")

    total_audio = 0
    total_slot = 0
    section_issues = 0

    for i, (name, text) in enumerate(sections):
        audio_dur = audio_durations.get(name, 0)
        total_audio += audio_dur

        # Calculate slot duration from timestamps
        if timestamps:
            start = timestamps.get(name, 0)
            # Find next section's timestamp
            next_name = section_names[i + 1] if i + 1 < len(section_names) else None
            if next_name and next_name in timestamps:
                slot_dur = timestamps[next_name] - start
            else:
                slot_dur = audio_dur + 5  # last section: estimate
            total_slot += slot_dur
        else:
            slot_dur = audio_dur + 2  # no timestamps: estimate with 2s buffer

        idle = slot_dur - audio_dur

        # Status
        if name not in timestamps and timestamps:
            status = f"{RED}MISSING TIMESTAMP{NC}"
            section_issues += 1
        elif idle < 0:
            status = f"{RED}OVERFLOW by {-idle:.1f}s{NC}"
            errors.append(
                f"[{name}] audio {audio_dur:.1f}s overflows slot {slot_dur:.1f}s"
            )
            section_issues += 1
        elif idle > args.max_idle:
            status = f"{YELLOW}IDLE {idle:.1f}s{NC}"
            warnings.append(f"[{name}] {idle:.1f}s idle (max {args.max_idle}s)")
            section_issues += 1
        else:
            status = f"{GREEN}OK{NC} ({idle:.1f}s pause)"

        print(
            f"  {name:<25} {audio_dur:>5.1f}s  {slot_dur:>5.1f}s  {idle:>5.1f}s  {status}"
        )

    print()
    print(f"  {CYAN}Total audio:{NC}  {total_audio:.1f}s")
    if timestamps:
        print(f"  {CYAN}Total video:{NC}  {total_slot:.1f}s")
        print(f"  {CYAN}Coverage:{NC}     {total_audio / total_slot * 100:.0f}%")
    print()

    # ── Check 3: Overlap detection ─────────────────────────────────────
    print(f"{BOLD}Check 3: Overlap Detection{NC}")

    overlaps = 0
    if timestamps:
        for i, (name, _) in enumerate(sections):
            if name not in timestamps:
                continue
            start = timestamps[name]
            audio_dur = audio_durations.get(name, 0)
            end = start + audio_dur

            next_name = section_names[i + 1] if i + 1 < len(section_names) else None
            if next_name and next_name in timestamps:
                next_start = timestamps[next_name]
                if end > next_start:
                    overlap = end - next_start
                    msg = f"[{name}] ends at {end:.1f}s but [{next_name}] starts at {next_start:.1f}s (overlap: {overlap:.1f}s)"
                    errors.append(msg)
                    print(f"  {RED}OVERLAP{NC} {msg}")
                    overlaps += 1

    if overlaps == 0:
        print(f"  {GREEN}PASS{NC} No overlapping audio segments")
    print()

    # ── Summary ────────────────────────────────────────────────────────
    print(f"{BOLD}{'=' * 80}{NC}")
    if errors:
        print(f"{RED}FAILED{NC} — {len(errors)} error(s), {len(warnings)} warning(s)")
        for e in errors:
            print(f"  {RED}✗{NC} {e}")
        for w in warnings:
            print(f"  {YELLOW}⚠{NC} {w}")
        print()
        return 1
    elif warnings:
        print(f"{YELLOW}PASSED with warnings{NC} — {len(warnings)} warning(s)")
        for w in warnings:
            print(f"  {YELLOW}⚠{NC} {w}")
        print()
        return 0
    else:
        print(
            f"{GREEN}PASSED{NC} — all {len(sections)} sections aligned (< {args.max_idle}s idle)"
        )
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
