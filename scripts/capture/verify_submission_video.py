#!/usr/bin/env python3
"""Fail when rendered submission segments regress visually.

This checks the two bugs that metadata-only validation missed:
- narrated cards must contain visible light text;
- browser shots must not contain Playwright's neutral-gray padding.
"""

import argparse
import json
import subprocess
from pathlib import Path

SAMPLE_WIDTH = 384
SAMPLE_HEIGHT = 216
EXPECTED_WIDTH = 1920
EXPECTED_HEIGHT = 1080
MAX_GRAY_PADDING_FRACTION = 0.10
MIN_CARD_TEXT_FRACTION = 0.0005


def run(command: list[str]) -> bytes:
    """Run a media probe and return stdout."""
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{stderr}")
    return result.stdout


def dimensions(path: Path) -> tuple[int, int]:
    """Return the first video stream's coded dimensions."""
    payload = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ]
    )
    stream = json.loads(payload)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def sampled_pixels(path: Path, timestamp: float = 3.0) -> list[tuple[int, int, int]]:
    """Decode one small RGB frame for deterministic pixel checks."""
    payload = run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-ss",
            str(timestamp),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    expected = SAMPLE_WIDTH * SAMPLE_HEIGHT * 3
    if len(payload) != expected:
        raise RuntimeError(f"Expected {expected} RGB bytes from {path}, got {len(payload)}")
    return list(zip(payload[0::3], payload[1::3], payload[2::3], strict=True))


def neutral_gray_fraction(pixels: list[tuple[int, int, int]]) -> float:
    """Measure the recorder's approximately RGB(128, 128, 128) padding."""
    padded = sum(
        105 <= red <= 150 and abs(red - green) <= 3 and abs(green - blue) <= 3
        for red, green, blue in pixels
    )
    return padded / len(pixels)


def visible_text_fraction(pixels: list[tuple[int, int, int]]) -> float:
    """Measure bright neutral or colored glyph pixels on a dark card."""
    text = sum(max(red, green, blue) >= 120 for red, green, blue in pixels)
    return text / len(pixels)


def verify(segment_dir: Path) -> list[str]:
    """Return visual contract violations for segments A through I."""
    errors: list[str] = []
    for shot in "ABCDEFGHI":
        path = segment_dir / f"seg-{shot}.mp4"
        if not path.is_file():
            errors.append(f"{path}: missing")
            continue
        actual_dimensions = dimensions(path)
        if actual_dimensions != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
            errors.append(
                f"seg-{shot}: expected 1920x1080, got {actual_dimensions[0]}x{actual_dimensions[1]}"
            )
            continue
        pixels = sampled_pixels(path)
        if shot in "AGHI":
            text_fraction = visible_text_fraction(pixels)
            if text_fraction < MIN_CARD_TEXT_FRACTION:
                errors.append(
                    f"seg-{shot}: no visible card text (light-pixel fraction {text_fraction:.5f})"
                )
        else:
            gray_fraction = neutral_gray_fraction(pixels)
            if gray_fraction > MAX_GRAY_PADDING_FRACTION:
                errors.append(
                    f"seg-{shot}: neutral-gray padding occupies {gray_fraction:.1%} of the frame"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("segment_dir", type=Path)
    args = parser.parse_args()
    errors = verify(args.segment_dir)
    if errors:
        print("VISUAL VERIFICATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("VISUAL VERIFICATION PASSED: A/G/H/I text visible; B-F fill the frame")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
