#!/usr/bin/env python3
"""
Validate narration-to-video alignment and produce an action plan.

The validation compares narration durations against video slot durations
and outputs exactly what needs to change to achieve perfect alignment.

Algorithm (converges in 2 iterations max):
  1. For each slot: target_slot = max(UI_time, narration + 1.3s)
  2. If narration < UI_time - 1.3s → ACTION: add narration text
  3. If narration > UI_time → ACTION: regenerate video with longer wait
  4. After fixing narration (iteration 1), video slots adjust (iteration 2)

Usage:
    python3 validate-alignment.py
    python3 validate-alignment.py --timestamps walkthrough-timestamps.json
    python3 validate-alignment.py --narration narrations/walkthrough-demo.txt
"""

import argparse
import json
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
DIM = "\033[2m"

MAX_IDLE_S = 1.3


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
    """~15 chars/second at speed 1.0."""
    return (len(text) / 15.0) / speed


def chars_for_duration(seconds: float, speed: float = 1.0) -> int:
    """How many chars of narration text fill N seconds."""
    return int(seconds * 15.0 * speed)


def main():
    parser = argparse.ArgumentParser(description="Validate narration-video alignment")
    parser.add_argument("--timestamps", default=None)
    parser.add_argument("--narration", default=None)
    parser.add_argument("--audio-dir", default=None)
    parser.add_argument("--max-idle", type=float, default=MAX_IDLE_S)
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
    max_idle = args.max_idle

    print()
    print(f"{BOLD}{'=' * 90}{NC}")
    print(f"{BOLD}  Narration-Video Alignment Validation{NC}")
    print(f"{BOLD}{'=' * 90}{NC}")
    print()

    # ── Load data ──────────────────────────────────────────────────────
    if not narr_file.exists():
        print(f"{RED}FAIL{NC} Narration file not found: {narr_file}")
        return 1
    sections = parse_narration_sections(str(narr_file))
    section_names = [name for name, _ in sections]
    section_texts = {name: text for name, text in sections}

    timestamps = {}
    if ts_file.exists():
        ts_data = json.loads(ts_file.read_text())
        timestamps = {e["step"]: e["time"] for e in ts_data}

    # Audio durations
    audio_durations = {}
    has_cached = False
    for name, text in sections:
        seg_file = audio_dir / f"{name}.mp3"
        if seg_file.exists():
            audio_durations[name] = get_audio_duration(str(seg_file))
            has_cached = True
        else:
            audio_durations[name] = estimate_tts_duration(text)

    dur_label = "cached" if has_cached else "est"
    ts_label = f"{len(timestamps)} steps" if timestamps else "none"
    print(f"  {CYAN}Narration:{NC}  {narr_file.name} ({len(sections)} sections)")
    print(f"  {CYAN}Timestamps:{NC} {ts_file.name} ({ts_label})")
    print(f"  {CYAN}Audio:{NC}      {dur_label}")
    print()

    # ── Check 1: Structure ─────────────────────────────────────────────
    missing_ts = [n for n in section_names if n not in timestamps] if timestamps else []
    orphaned_ts = (
        [n for n in timestamps if n not in section_names] if timestamps else []
    )
    struct_ok = not missing_ts and not orphaned_ts

    if missing_ts:
        print(f"  {RED}STRUCTURE{NC} Missing markStep() for: {', '.join(missing_ts)}")
        print(
            f"  {DIM}Action: Move markStep('{missing_ts[0]}') outside conditional blocks in the test{NC}"
        )
        print()

    # ── Alignment table ────────────────────────────────────────────────
    print(
        f"{BOLD}  {'Section':<22} {'Narr':>6} {'Slot':>6} {'Idle':>6}  {'Target':>6}  Status & Action{NC}"
    )
    print(f"  {'─' * 22} {'─' * 6} {'─' * 6} {'─' * 6}  {'─' * 6}  {'─' * 35}")

    actions = []
    total_narr = 0
    total_slot = 0
    all_ok = True

    for i, (name, text) in enumerate(sections):
        narr_dur = audio_durations.get(name, 0)
        total_narr += narr_dur

        # Slot duration from timestamps
        if timestamps and name in timestamps:
            start = timestamps[name]
            next_name = section_names[i + 1] if i + 1 < len(section_names) else None
            if next_name and next_name in timestamps:
                slot_dur = timestamps[next_name] - start
            else:
                slot_dur = max(narr_dur + max_idle, 10)  # last section
            total_slot += slot_dur
        elif timestamps:
            slot_dur = 0  # missing timestamp
            total_slot += 0
        else:
            slot_dur = narr_dur + 2
            total_slot += slot_dur

        # Target = what the slot SHOULD be
        target = narr_dur + max_idle

        idle = slot_dur - narr_dur

        # Determine status and action
        if name not in timestamps and timestamps:
            status = f"{RED}NO TIMESTAMP{NC}"
            action = f"Fix: move markStep('{name}') outside conditionals"
            actions.append(("ERROR", name, action))
            all_ok = False
        elif idle < 0:
            overflow = -idle
            status = f"{RED}OVERFLOW {overflow:.1f}s{NC}"
            action = f"Regen video: slot needs +{overflow + max_idle:.1f}s wait"
            actions.append(
                ("REGEN_VIDEO", name, f"Add {overflow + max_idle:.1f}s extra wait")
            )
            all_ok = False
        elif idle > max_idle:
            gap = idle - max_idle
            chars_needed = chars_for_duration(gap)
            status = f"{YELLOW}IDLE {idle:.1f}s{NC}"
            action = f"Add ~{chars_needed} chars ({gap:.1f}s) narration"
            actions.append(
                ("ADD_NARRATION", name, f"Add ~{chars_needed} chars to fill {gap:.1f}s")
            )
            all_ok = False
        else:
            status = f"{GREEN}OK{NC} {idle:.1f}s"
            action = ""

        narr_str = f"{narr_dur:.1f}s"
        slot_str = f"{slot_dur:.1f}s" if slot_dur > 0 else "  - "
        idle_str = f"{idle:.1f}s" if name in timestamps or not timestamps else "  - "
        target_str = f"{target:.1f}s"

        line = f"  {name:<22} {narr_str:>6} {slot_str:>6} {idle_str:>6}  {target_str:>6}  {status}"
        if action:
            line += f"  {DIM}{action}{NC}"
        print(line)

    print()
    coverage = (total_narr / total_slot * 100) if total_slot > 0 else 0
    print(f"  {CYAN}Total narration:{NC} {total_narr:.1f}s")
    print(f"  {CYAN}Total video:{NC}     {total_slot:.1f}s")
    print(f"  {CYAN}Coverage:{NC}        {coverage:.0f}%")
    print(
        f"  {CYAN}Target:{NC}          >{100 - max_idle / total_slot * len(sections) * 100:.0f}% coverage"
        if total_slot > 0
        else ""
    )
    print()

    # ── Overlap check ──────────────────────────────────────────────────
    overlaps = []
    if timestamps:
        for i, (name, _) in enumerate(sections):
            if name not in timestamps:
                continue
            start = timestamps[name]
            end = start + audio_durations.get(name, 0)
            next_name = section_names[i + 1] if i + 1 < len(section_names) else None
            if next_name and next_name in timestamps:
                next_start = timestamps[next_name]
                if end > next_start:
                    overlaps.append((name, next_name, end - next_start))

    if overlaps:
        print(f"  {RED}OVERLAPS:{NC}")
        for a, b, dur in overlaps:
            print(f"    [{a}] overlaps [{b}] by {dur:.1f}s")
            actions.append(
                (
                    "REGEN_VIDEO",
                    a,
                    f"Overlap with [{b}] by {dur:.1f}s — needs longer slot",
                )
            )
        print()

    # ── Action plan ────────────────────────────────────────────────────
    print(f"{BOLD}{'=' * 90}{NC}")

    if all_ok and not overlaps and struct_ok:
        print(
            f"{GREEN}PASSED{NC} — all {len(sections)} sections aligned (idle < {max_idle}s, no overlaps)"
        )
        print()
        return 0

    # Group actions by type
    narr_actions = [(n, a) for t, n, a in actions if t == "ADD_NARRATION"]
    video_actions = [(n, a) for t, n, a in actions if t == "REGEN_VIDEO"]
    struct_actions = [(n, a) for t, n, a in actions if t == "ERROR"]

    print()
    if struct_actions:
        print(f"{RED}Step 0: Fix test structure{NC} (must fix before anything else)")
        for name, action in struct_actions:
            print(f"  - [{name}] {action}")
        print()

    if narr_actions:
        print(f"{YELLOW}Step 1: Expand narration{NC} (add text to fill idle gaps)")
        for name, action in narr_actions:
            current_chars = len(section_texts.get(name, ""))
            print(f"  - [{name}] {action} (currently {current_chars} chars)")
        print()
        print(
            f"  {DIM}After editing narrations, run: python3 validate-alignment.py{NC}"
        )
        print(f"  {DIM}Then proceed to Step 2 if needed.{NC}")
        print()

    if video_actions:
        needs_regen = len(video_actions)
        print(
            f"{RED}Step 2: Regenerate video{NC} ({needs_regen} slot(s) need longer video time)"
        )
        for name, action in video_actions:
            print(f"  - [{name}] {action}")
        print()
        print(
            f"  {DIM}Run: ./local_experiments/run-playwright-demo.sh --cluster-suffix <X> --test walkthrough-demo --sync{NC}"
        )
        print(
            f"  {DIM}The --sync flag will add extra waits to match narration durations.{NC}"
        )
        print()

    if not video_actions and narr_actions:
        print(
            f"{CYAN}After Step 1:{NC} If all narration gaps are filled, run --sync once"
        )
        print(
            f"  to regenerate video with adjusted timing. Should pass in 1 iteration."
        )
        print()
    elif video_actions and not narr_actions:
        print(f"{CYAN}After Step 2:{NC} Run validation again. Should pass immediately.")
        print()
    elif video_actions and narr_actions:
        print(
            f"{CYAN}Resolution:{NC} Fix narration first (Step 1), then --sync (Step 2)."
        )
        print(f"  Converges in 2 iterations max.")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
