#!/usr/bin/env python3
"""Assemble the submission video: 4K sources -> 1080p, narrated cards, no loops."""
import subprocess, os
from pathlib import Path

OUT = Path("/tmp/po-video-final-v2"); OUT.mkdir(exist_ok=True)
CAP = Path("/tmp/po-captures-4k")
NAR = Path.home() / "po-narration-kokoro"
W, H, FPS = 1920, 1080, 30
FONT = "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf"
DUR = {"A": 15.456, "B": 31.584, "C": 27.696, "D": 19.416,
       "E": 10.488, "F": 10.368, "G": 34.416, "H": 17.880}

def run(cmd):
    cmd = [str(c) for c in cmd]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(cmd[:8])}\n{p.stderr[-1200:]}")

# --- encoder selection (same for ALL segments) ---
# h264_vaapi errored (-22) with drawtext-in-chain on this box; proven fallback:
ENCODER = ["-vf", "scale=1920:1080:flags=lanczos,unsharp=5:5:0.6:5:5:0.0",
           "-c:v", "libopenh264", "-b:v", "14M"]
print("encoder: libopenh264")

def encode_args(dur):
    return ENCODER + ["-r", str(FPS), "-t", f"{dur:.3f}"]

def text_card(shot, lines):
    """4K gradient card + narrated audio (existing Kokoro clip), apad to length."""
    dur = DUR[shot]
    out = OUT / f"seg-{shot}.mp4"
    draw, y = [], 760  # 4K canvas: y is 2x the 1080 position
    for entry in lines:
        text, size, dy = entry[0], int(entry[1]) * 2, entry[2]
        color = entry[3] if len(entry) > 3 else "0xEDEDF2"
        escaped = text.replace(":", r"\:").replace("'", "")
        draw.append(f"drawtext=text='{escaped}':fontcolor={color}:"
                    f"fontsize={size}:x=(w-text_w)/2:y={int(y)}:line_spacing=28:"
                    f"fontfile={FONT}")
        y += (int(dy) * 2) if dy else size + 36
    vf = ",".join(draw)
    run(["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i",
         f"gradients=s=3840x2160:r={FPS}:c0=0x0d0d17:c1=0x1a1a2e:duration={dur}",
         "-i", str(NAR / f"shot-{shot}.mp3"),
         "-vf", vf, *encode_args(dur),
         "-af", "apad", "-c:a", "aac", "-b:a", "160k",
         "-map", "0:v", "-map", "1:a", str(out)])
    return out, dur

def capture_seg(shot, clip):
    """4K capture -> 1080p, trimmed to narration length. NO stream_loop."""
    dur = DUR[shot]
    out = OUT / f"seg-{shot}.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error",
         "-i", str(clip),
         "-i", str(NAR / f"shot-{shot}.mp3"),
         *encode_args(dur),
         "-af", "apad", "-c:a", "aac", "-b:a", "160k",
         "-map", "0:v", "-map", "1:a", str(out)])
    return out, dur

segs = []
o, d = text_card("A", [
    ("ZERO UNAPPROVED WRITES", 64, 0),
    ("", 20, 30),
    ("provably fail-closed under forged, stale, and replayed inputs,", 30, 0),
    ("across a real process boundary", 30, 60),
    ("", 20, 40),
    ("a Strands agent for real work — human-approved writes", 26, 0),
]); segs.append(("A", o, d))

for shot, clip in [("B", "shot-B-intake.webm"), ("C", "shot-C-board.webm"),
                   ("D", "shot-D-interrupt.webm"), ("E", "shot-E-reject.webm"),
                   ("F", "shot-F-approve.webm")]:
    o, d = capture_seg(shot, CAP / clip); segs.append((shot, o, d))

attack_lines = [
    ("$ resume --decision approve   (proposal_hash edited to 64 x 'f')", 30, 48, "0xB8BBD0"),
    ("  ValueError: Checkpoint proposal does not match canonical persisted evidence", 27, 44, "0xFF6B6B"),
    ("  exit=1   no report written", 27, 34, "0xFFD166"),
    ("", 14, 22, "0xEDEDF2"),
    ("$ resume --decision approve   (legitimate approval, fresh runtime)", 30, 48, "0xB8BBD0"),
    ("  FINAL_STATE_REVISION=2   WORKFLOW_PASSED=true   exit=0", 27, 44, "0x9BE89B"),
    ("", 14, 22, "0xEDEDF2"),
    ("$ resume --decision approve   (the same approval, replayed)", 30, 48, "0xB8BBD0"),
    ("  ValueError: Domain state changed after the interrupt checkpoint", 27, 44, "0xFF6B6B"),
    ("  exit=1   no report written — the attempt is in the audit log", 27, 34, "0xFFD166"),
]
o, d = text_card("G", attack_lines); segs.append(("G", o, d))

o, d = text_card("H", [
    ("The scheduling is the demo.", 44, 70),
    ("The governance layer is the product.", 44, 90),
    ("", 24, 40),
    ("one gated write  ·  immutable proposals  ·  hash-bound approval", 28, 60),
    ("fail-closed across restarts  ·  complete audit chain", 28, 80),
    ("", 24, 40),
    ("ZERO UNAPPROVED WRITES", 40, 60),
    ("github.com/TheAmericanMaker/production-orchestrator", 26, 40),
]); segs.append(("H", o, d))

with open(OUT / "concat.txt", "w") as f:
    for _, o, _ in segs:
        f.write(f"file '{o}'\n")
run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
     "-i", str(OUT / "concat.txt"), "-c", "copy",
     str(OUT / "submission-video.mp4")])
p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
                    "-of", "csv=p=0", str(OUT / "submission-video.mp4")],
                   capture_output=True, text=True)
print("final:", p.stdout.strip())