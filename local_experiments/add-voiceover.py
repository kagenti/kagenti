#!/usr/bin/env python3
"""
Add voiceover to a recorded Playwright video using OpenAI TTS + FFmpeg.

Usage:
    python3 add-voiceover.py <video-file>

Environment:
    OPENAI_API_KEY  - Required. OpenAI API key for TTS.

The script looks for a narration text file matching the video name:
    1. local_experiments/narrations/<test-name>.txt
    2. local_experiments/narrations/default.txt

If no narration file found, generates a generic one.

Output:
    <video-file-without-ext>_voiceover.mp4

Dependencies:
    - openai Python package (pip install openai)
    - ffmpeg CLI tool
"""

import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path


def warn(msg: str) -> None:
    print(f"\033[1;33m[voiceover-warn]\033[0m {msg}", file=sys.stderr)


def info(msg: str) -> None:
    print(f"\033[0;36m[voiceover]\033[0m {msg}")


def _concat_segments(segment_files: list, output_path: Path) -> None:
    """Concatenate audio segments with 1s silence gaps using ffmpeg."""
    import tempfile

    # Create concat list file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for _, seg_path in segment_files:
            f.write(f"file '{seg_path}'\n")
        concat_list = f.name

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_list,
            "-c",
            "copy",
            "-loglevel",
            "warning",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        os.unlink(concat_list)
    except OSError:
        pass


def main() -> int:
    if len(sys.argv) < 2:
        warn("Usage: add-voiceover.py <video-file>")
        return 1

    video_path = Path(sys.argv[1])
    if not video_path.exists():
        warn(f"Video file not found: {video_path}")
        return 1

    # Check OPENAI_API_KEY
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        warn("OPENAI_API_KEY not set — skipping voiceover")
        return 0

    # Check ffmpeg
    if not shutil.which("ffmpeg"):
        warn("ffmpeg not found in PATH — skipping voiceover")
        return 0

    # Import openai (available via uv run --with openai, or pip install openai)
    try:
        from openai import OpenAI
    except ImportError:
        warn("openai package not installed. Run: uv pip install openai")
        return 0

    # Find narration text
    script_dir = Path(__file__).parent
    narrations_dir = script_dir / "narrations"

    # Extract test name from video filename (e.g., "walkthrough-demo-..._2026-02-08_14-30.webm")
    video_stem = video_path.stem
    # Match against narration files by prefix
    test_name = None
    for narration_file in sorted(
        narrations_dir.glob("*.txt"), key=lambda f: len(f.stem), reverse=True
    ):
        if narration_file.stem in video_stem or video_stem.startswith(
            narration_file.stem
        ):
            test_name = narration_file.stem
            break
    # Fallback: try extracting from the stem
    if not test_name:
        parts = video_stem.rsplit("_", 2)
        test_name = parts[0] if len(parts) >= 2 else video_stem

    narration_file = narrations_dir / f"{test_name}.txt"
    if not narration_file.exists():
        narration_file = narrations_dir / "default.txt"
    if not narration_file.exists():
        info("No narration file found, using generic narration")
        narration_raw = f"This is a demo of the K-agenti platform, showing the {test_name.replace('-', ' ')} functionality."
    else:
        narration_raw = narration_file.read_text().strip()
        info(f"Using narration: {narration_file}")

    # Parse sectioned narration format: [section_name]\ntext
    import re

    sections = []
    current_section = None
    current_text = []
    for line in narration_raw.split("\n"):
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

    # If no sections found, treat as single block
    if not sections:
        sections = [("full", narration_raw)]

    # Load timestamps from walkthrough test (if available)
    timestamps_file = script_dir / "walkthrough-timestamps.json"
    timestamps = {}
    if timestamps_file.exists():
        import json

        ts_data = json.loads(timestamps_file.read_text())
        # Timestamps are relative to test start (Date.now()), but video starts
        # a few seconds before test code runs (browser launch).
        # Use the first timestamp as video offset baseline.
        raw_timestamps = {entry["step"]: entry["time"] for entry in ts_data}
        # Don't adjust — the video recording starts close to when the page
        # first navigates, which is near the 'intro' timestamp.
        # Just use raw values; the first step at ~1-3s is fine.
        timestamps = raw_timestamps
        info(f"Loaded {len(timestamps)} step timestamps")
        for step, t in timestamps.items():
            info(f"  {step}: {t:.1f}s")

    # Voice configuration
    tts_model = os.environ.get("TTS_MODEL", "tts-1-hd")
    tts_voice = os.environ.get("TTS_VOICE", "onyx")
    tts_speed = float(os.environ.get("TTS_SPEED", "1.0"))

    info(
        f"Generating voiceover (model={tts_model}, voice={tts_voice}, speed={tts_speed})..."
    )
    info(f"Narration has {len(sections)} sections")

    client = OpenAI(api_key=api_key)

    # Generate TTS for each section
    segment_files = []
    for section_name, section_text in sections:
        try:
            response = client.audio.speech.create(
                model=tts_model,
                voice=tts_voice,
                speed=tts_speed,
                input=section_text,
            )
            seg_path = video_path.parent / f".tmp_segment_{section_name}.mp3"
            seg_path.write_bytes(response.content)
            segment_files.append((section_name, seg_path))
            info(f"  [{section_name}] generated ({len(section_text)} chars)")
        except Exception as e:
            warn(f"  [{section_name}] TTS failed: {e}")

    if not segment_files:
        warn("No audio segments generated")
        return 0

    # Get duration of each segment
    def get_audio_duration(path: Path) -> float:
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
                    str(path),
                ],
                capture_output=True,
                text=True,
            )
            return float(r.stdout.strip()) if r.returncode == 0 else 0
        except Exception:
            return 0

    segment_durations = {}
    for section_name, seg_path in segment_files:
        dur = get_audio_duration(seg_path)
        segment_durations[section_name] = dur

    # Build the final audio track with silence gaps matching timestamps
    audio_path = video_path.with_stem(video_stem + "_narration").with_suffix(".mp3")

    try:
        if timestamps and len(timestamps) > 1:
            # Check for overlaps and truncate segments if needed
            section_names = [name for name, _ in segment_files]
            for i, (section_name, seg_path) in enumerate(segment_files):
                seg_dur = segment_durations.get(section_name, 0)
                seg_start = timestamps.get(section_name, 0)

                # Find next section start time
                next_start = None
                for j in range(i + 1, len(segment_files)):
                    ns = segment_files[j][0]
                    if ns in timestamps:
                        next_start = timestamps[ns]
                        break

                if next_start is not None:
                    available = next_start - seg_start
                    if seg_dur > available and available > 0:
                        warn(
                            f"  [{section_name}] narration {seg_dur:.1f}s > gap {available:.1f}s — truncating with fade"
                        )
                        truncated = seg_path.with_stem(seg_path.stem + "_trunc")
                        fade_start = max(0, available - 0.5)
                        subprocess.run(
                            [
                                "ffmpeg",
                                "-y",
                                "-i",
                                str(seg_path),
                                "-af",
                                f"afade=t=out:st={fade_start}:d=0.5",
                                "-t",
                                str(available),
                                "-loglevel",
                                "warning",
                                str(truncated),
                            ],
                            capture_output=True,
                            text=True,
                        )
                        if truncated.exists():
                            seg_path.unlink()
                            truncated.rename(seg_path)
                            segment_durations[section_name] = available
                    else:
                        info(
                            f"  [{section_name}] {seg_dur:.1f}s fits in {available:.1f}s gap"
                        )

            # Build ffmpeg filter to place segments at correct timestamps
            inputs = []
            filter_parts = []
            for i, (section_name, seg_path) in enumerate(segment_files):
                inputs.extend(["-i", str(seg_path)])
                delay_ms = int(timestamps.get(section_name, 0) * 1000)
                filter_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[s{i}]")

            # Mix all delayed segments
            mix_inputs = "".join(f"[s{i}]" for i in range(len(segment_files)))
            filter_parts.append(
                f"{mix_inputs}amix=inputs={len(segment_files)}:normalize=0[out]"
            )
            filter_str = ";".join(filter_parts)

            result = subprocess.run(
                ["ffmpeg", "-y"]
                + inputs
                + [
                    "-filter_complex",
                    filter_str,
                    "-map",
                    "[out]",
                    "-loglevel",
                    "warning",
                    str(audio_path),
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                warn(f"FFmpeg segment assembly failed: {result.stderr}")
                _concat_segments(segment_files, audio_path)
        else:
            _concat_segments(segment_files, audio_path)

        info(f"Narration audio: {audio_path}")
    finally:
        for _, seg_path in segment_files:
            try:
                seg_path.unlink()
            except OSError:
                pass

    # Get video duration to pad audio with silence
    video_duration = None
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(video_path),
            ],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            video_duration = float(probe.stdout.strip())
            info(f"Video duration: {video_duration:.1f}s")
    except Exception:
        pass

    # Get audio duration
    audio_duration = None
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            audio_duration = float(probe.stdout.strip())
            info(f"Narration duration: {audio_duration:.1f}s")
    except Exception:
        pass

    # Composite video + audio with FFmpeg
    # Pad audio with silence to match video length (so video doesn't get truncated)
    output_path = video_path.with_stem(video_stem + "_voiceover").with_suffix(".mp4")

    info(f"Compositing video + audio with FFmpeg...")
    try:
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
        ]

        if video_duration and audio_duration and video_duration > audio_duration:
            # Pad narration audio with silence to match video length
            pad_duration = video_duration - audio_duration
            info(f"Padding narration with {pad_duration:.1f}s of silence")
            ffmpeg_cmd += [
                "-filter_complex",
                f"[1:a]apad=whole_dur={video_duration}[a]",
                "-map",
                "0:v",
                "-map",
                "[a]",
            ]
        else:
            ffmpeg_cmd += [
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-shortest",
            ]

        ffmpeg_cmd += [
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-loglevel",
            "warning",
            str(output_path),
        ]

        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            warn(f"FFmpeg failed: {result.stderr}")
            return 0

        info(f"Voiceover video: {output_path}")
    except Exception as e:
        warn(f"FFmpeg execution failed: {e}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
