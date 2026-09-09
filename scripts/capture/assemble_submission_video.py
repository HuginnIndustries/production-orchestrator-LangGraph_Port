#!/usr/bin/env python3
"""Assemble the narrated 1080p submission video without looping clips."""

import subprocess
from pathlib import Path

OUT = Path("/tmp/po-video-final-v3")
OUT.mkdir(exist_ok=True)
CAP = Path("/tmp/po-captures-1080p")
NAR = Path.home() / "po-narration-kokoro"
WIDTH, HEIGHT, FPS = 1920, 1080, 30
FONT = "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf"
DUR = {
    "A": 15.456,
    "B": 31.584,
    "C": 27.696,
    "D": 19.416,
    "E": 10.488,
    "F": 10.368,
    "G": 34.416,
    "H": 17.880,
}
CAPTURE_FILTER = (
    "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,"
    "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
    "setsar=1,format=yuv420p,unsharp=5:5:0.35:5:5:0.0"
)


def run(command: list[str | Path]) -> None:
    """Run a media command and surface its useful error tail."""
    normalized = [str(part) for part in command]
    result = subprocess.run(normalized, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(normalized[:8])}\n{result.stderr[-1600:]}")


def encode_args(duration: float, video_filter: str) -> list[str]:
    """Return one video-filter chain and common deterministic output settings."""
    return [
        "-vf",
        video_filter,
        "-c:v",
        "libopenh264",
        "-b:v",
        "14M",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
        "-t",
        f"{duration:.3f}",
    ]


def text_card(
    shot: str,
    lines: list[tuple[str, int, int] | tuple[str, int, int, str]],
) -> tuple[Path, float]:
    """Render a 1080p gradient card with visible text and its narration."""
    duration = DUR[shot]
    output = OUT / f"seg-{shot}.mp4"
    filters: list[str] = []
    y = 380
    for index, entry in enumerate(lines):
        text, size, advance = entry[:3]
        color = entry[3] if len(entry) > 3 else "0xEDEDF2"
        if text:
            text_path = OUT / f"card-{shot}-{index:02d}.txt"
            text_path.write_text(text)
            filters.append(
                f"drawtext=textfile={text_path}:expansion=none:fontcolor={color}:"
                f"fontsize={size}:x=(w-text_w)/2:y={y}:line_spacing=14:"
                f"fontfile={FONT}"
            )
        y += advance if advance else size + 18
    filters.extend(["setsar=1", "format=yuv420p"])
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            (f"gradients=s={WIDTH}x{HEIGHT}:r={FPS}:c0=0x0d0d17:c1=0x1a1a2e:duration={duration}"),
            "-i",
            NAR / f"shot-{shot}.mp3",
            "-map",
            "0:v",
            "-map",
            "1:a",
            *encode_args(duration, ",".join(filters)),
            "-af",
            "apad",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            output,
        ]
    )
    return output, duration


def capture_segment(shot: str, clip: Path) -> tuple[Path, float]:
    """Normalize a full-frame browser capture and pair it with narration."""
    duration = DUR[shot]
    output = OUT / f"seg-{shot}.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            clip,
            "-i",
            NAR / f"shot-{shot}.mp3",
            "-map",
            "0:v",
            "-map",
            "1:a",
            *encode_args(duration, CAPTURE_FILTER),
            "-af",
            "apad",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            output,
        ]
    )
    return output, duration


def main() -> None:
    """Build all eight segments and concatenate their identical streams."""
    segments: list[tuple[str, Path, float]] = []
    output, duration = text_card(
        "A",
        [
            ("ZERO UNAPPROVED WRITES", 64, 0),
            ("", 20, 30),
            (
                "provably fail-closed under forged, stale, and replayed inputs,",
                30,
                0,
            ),
            ("across a real process boundary", 30, 60),
            ("", 20, 40),
            ("a Strands agent for real work — human-approved writes", 26, 0),
        ],
    )
    segments.append(("A", output, duration))

    captures = [
        ("B", "shot-B-intake.webm"),
        ("C", "shot-C-board.webm"),
        ("D", "shot-D-interrupt.webm"),
        ("E", "shot-E-reject.webm"),
        ("F", "shot-F-approve.webm"),
    ]
    for shot, filename in captures:
        output, duration = capture_segment(shot, CAP / filename)
        segments.append((shot, output, duration))

    output, duration = text_card(
        "G",
        [
            (
                "$ resume --decision approve   (proposal_hash edited to 64 x 'f')",
                30,
                48,
                "0xB8BBD0",
            ),
            (
                "  ValueError: Checkpoint proposal does not match canonical persisted evidence",
                27,
                44,
                "0xFF6B6B",
            ),
            ("  exit=1   no report written", 27, 34, "0xFFD166"),
            ("", 14, 22, "0xEDEDF2"),
            (
                "$ resume --decision approve   (legitimate approval, fresh runtime)",
                30,
                48,
                "0xB8BBD0",
            ),
            (
                "  FINAL_STATE_REVISION=2   WORKFLOW_PASSED=true   exit=0",
                27,
                44,
                "0x9BE89B",
            ),
            ("", 14, 22, "0xEDEDF2"),
            (
                "$ resume --decision approve   (the same approval, replayed)",
                30,
                48,
                "0xB8BBD0",
            ),
            (
                "  ValueError: Domain state changed after the interrupt checkpoint",
                27,
                44,
                "0xFF6B6B",
            ),
            (
                "  exit=1   no report written — the attempt is in the audit log",
                27,
                34,
                "0xFFD166",
            ),
        ],
    )
    segments.append(("G", output, duration))

    output, duration = text_card(
        "H",
        [
            ("The scheduling is the demo.", 44, 70),
            ("The governance layer is the product.", 44, 90),
            ("", 24, 40),
            (
                "one gated write  ·  immutable proposals  ·  hash-bound approval",
                28,
                60,
            ),
            ("fail-closed across restarts  ·  complete audit chain", 28, 80),
            ("", 24, 40),
            ("ZERO UNAPPROVED WRITES", 40, 60),
            ("github.com/TheAmericanMaker/production-orchestrator", 26, 40),
        ],
    )
    segments.append(("H", output, duration))

    concat_path = OUT / "concat.txt"
    concat_path.write_text("".join(f"file '{output}'\n" for _, output, _ in segments))
    final_path = OUT / "submission-video.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_path,
            "-c",
            "copy",
            final_path,
        ]
    )
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-of",
            "csv=p=0",
            str(final_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise SystemExit(probe.stderr)
    print(f"final: {probe.stdout.strip()}")


if __name__ == "__main__":
    main()
