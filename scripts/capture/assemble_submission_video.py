#!/usr/bin/env python3
"""Assemble the narrated 1080p submission video without looping UI clips."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("/tmp/po-video-final-v5")
OUT.mkdir(exist_ok=True)
CAP = Path("/tmp/po-captures-1080p")
ASSETS = Path(__file__).with_name("assets")
EVIDENCE = ROOT / "evidence" / "agentcore-invocation-evidence.json"
BASE_NARRATION = Path.home() / "po-narration-kokoro"
PITCH_NARRATION = Path.home() / "po-narration-kokoro-v2"
WIDTH, HEIGHT, FPS = 1920, 1080, 30
FONT = "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf"
DUR = {
    "A": 45.456,
    "B": 31.584,
    "C": 27.696,
    "D": 19.416,
    "E": 10.488,
    "F": 10.368,
    "G": 34.416,
    "H": 40.128,
    "I": 19.440,
}
NARRATION = {
    **{shot: BASE_NARRATION / f"shot-{shot}.mp3" for shot in "BCDEFG"},
    "A": PITCH_NARRATION / "shot-A-intro.mp3",
    "H": PITCH_NARRATION / "shot-H-outro.mp3",
    "I": PITCH_NARRATION / "shot-I-agentcore.mp3",
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


def output_args(duration: float) -> list[str]:
    """Return common deterministic video and audio output settings."""
    return [
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
        "-af",
        "apad",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
    ]


def encode_args(duration: float, video_filter: str) -> list[str]:
    """Return one video-filter chain plus deterministic output settings."""
    return ["-vf", video_filter, *output_args(duration)]


def text_card(
    shot: str,
    lines: list[tuple[str, int, int] | tuple[str, int, int, str]],
) -> tuple[Path, float]:
    """Render a 1080p gradient card with visible text and narration."""
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
            (
                f"gradients=s={WIDTH}x{HEIGHT}:r={FPS}:c0=0x0d0d17:c1=0x1a1a2e:"
                f"x0=0:y0=0:x1={WIDTH - 1}:y1={HEIGHT - 1}:speed=0.01:duration={duration}"
            ),
            "-i",
            NARRATION[shot],
            "-map",
            "0:v",
            "-map",
            "1:a",
            *encode_args(duration, ",".join(filters)),
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
            NARRATION[shot],
            "-map",
            "0:v",
            "-map",
            "1:a",
            *encode_args(duration, CAPTURE_FILTER),
            output,
        ]
    )
    return output, duration


def render_svg(
    name: str,
    source: Path,
    replacements: dict[str, str] | None = None,
) -> Path:
    """Render a local SVG card to the final video raster."""
    render_source = source
    if replacements:
        content = source.read_text()
        for token, value in replacements.items():
            content = content.replace("{{" + token + "}}", value)
        if "{{" in content or "}}" in content:
            raise SystemExit(f"Unresolved template token in {source}")
        render_source = OUT / f"{name}.svg"
        render_source.write_text(content)
    output = OUT / f"{name}.png"
    run(
        [
            "inkscape",
            render_source,
            f"--export-filename={output}",
            f"--export-width={WIDTH}",
            f"--export-height={HEIGHT}",
        ]
    )
    return output


def evidence_replacements() -> dict[str, str]:
    """Return sanitized card values from verified AgentCore invocation evidence."""
    evidence = json.loads(EVIDENCE.read_text())
    reject_run = next(run_data for run_data in evidence["runs"] if "reject" in run_data)
    approve_run = next(run_data for run_data in evidence["runs"] if "approve" in run_data)
    rejected = reject_run["reject"]
    approved = approve_run["approve"]
    if not all(
        (
            rejected["workflow_passed"],
            rejected["process_boundary_proven"],
            approved["workflow_passed"],
            approved["process_boundary_proven"],
            rejected["plan_applied_count"] == 0,
            approved["plan_applied_count"] == 1,
            rejected["proposal_hash"] == approved["proposal_hash"],
        )
    ):
        raise SystemExit("AgentCore evidence does not satisfy the narrated proof contract")
    runtime_id = evidence["runtime_arn"].rsplit("/", maxsplit=1)[-1]
    return {
        "RUNTIME_ID": runtime_id,
        "ENDPOINT": evidence["endpoint"],
        "REJECT_PHASE": rejected["phase"],
        "REJECT_REVISION": str(rejected["state_revision"]),
        "REJECT_COUNT": str(rejected["plan_applied_count"]),
        "REJECT_PASSED": str(rejected["workflow_passed"]).lower(),
        "APPROVE_PHASE": approved["phase"],
        "APPROVE_REVISION": str(approved["state_revision"]),
        "APPROVE_COUNT": str(approved["plan_applied_count"]),
        "APPROVE_PASSED": str(approved["workflow_passed"]).lower(),
        "START_PID": str(approved["start_process_id"]),
        "RESUME_PID": str(approved["resume_process_id"]),
        "HASH_SHORT": approved["proposal_hash"][:8] + "…",
    }


def image_sequence_card(
    shot: str,
    scenes: list[tuple[Path, float]],
) -> tuple[Path, float]:
    """Pair one or more final-raster still scenes with continuous narration."""
    duration = DUR[shot]
    scene_total = sum(scene_duration for _, scene_duration in scenes)
    if abs(scene_total - duration) > 0.001:
        raise SystemExit(f"Shot {shot} scenes total {scene_total:.3f}s, expected {duration:.3f}s")
    command: list[str | Path] = ["ffmpeg", "-y", "-loglevel", "error"]
    for image, scene_duration in scenes:
        command.extend(
            [
                "-loop",
                "1",
                "-framerate",
                str(FPS),
                "-t",
                f"{scene_duration:.3f}",
                "-i",
                image,
            ]
        )
    command.extend(["-i", NARRATION[shot]])
    filters = [
        f"[{index}:v]fps={FPS},setsar=1,format=yuv420p[v{index}]" for index in range(len(scenes))
    ]
    if len(scenes) == 1:
        video_output = "v0"
    else:
        inputs = "".join(f"[v{index}]" for index in range(len(scenes)))
        filters.append(f"{inputs}concat=n={len(scenes)}:v=1:a=0[vout]")
        video_output = "vout"
    output = OUT / f"seg-{shot}.mp4"
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{video_output}]",
            "-map",
            f"{len(scenes)}:a",
            *output_args(duration),
            output,
        ]
    )
    run(command)
    return output, duration


def main() -> None:
    """Build nine segments and concatenate their identical streams."""
    intro_context = render_svg("intro-context", ASSETS / "intro-context.svg")
    intro_governance = render_svg("intro-governance", ASSETS / "intro-governance.svg")
    agentcore = render_svg(
        "agentcore-proof",
        ASSETS / "agentcore-proof.svg",
        evidence_replacements(),
    )
    architecture = render_svg("governance-architecture", ASSETS / "governance-architecture.svg")
    outro_title = render_svg("outro-title", ASSETS / "outro-title.svg")

    segments: list[tuple[str, Path, float]] = []
    output, duration = image_sequence_card(
        "A",
        [(intro_context, 29.5), (intro_governance, DUR["A"] - 29.5)],
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

    output, duration = image_sequence_card("I", [(agentcore, DUR["I"])])
    segments.append(("I", output, duration))

    output, duration = image_sequence_card(
        "H",
        [(architecture, 28.0), (outro_title, DUR["H"] - 28.0)],
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
