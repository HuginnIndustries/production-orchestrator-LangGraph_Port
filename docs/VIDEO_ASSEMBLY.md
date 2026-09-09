# Video assembly inventory — Production Orchestrator submission

Updated September 9, 2026. This document describes the corrected v3 capture and
assembly pipeline; it supersedes the padded v2 render.

## Final artifact

- Durable video: `~/Documents/Github/notes/submission-assets/submission-video.mp4`
- Durable segments: `~/Documents/Github/notes/submission-assets/segments/seg-A.mp4`
  through `seg-H.mp4`
- Scratch build: `/tmp/po-video-final-v3/`
- Format: H.264 video, AAC audio, 1920×1080, 30 fps, SAR 1:1, DAR 16:9
- Runtime: 167.44 seconds (2:47); below the five-minute limit
- Narration: `~/po-narration-kokoro/shot-A.mp3` through `shot-H.mp3`

Video binaries stay outside Git. The repository contains only the reproducible
capture, assembly, and verification tools.

## Shot inventory

| File | Shot | Content | Narration |
|---|---|---|---|
| `/tmp/po-captures-1080p/shot-B-intake.webm` (33.3s) | B (15.5–47.0s) | Intake card and activity feed, one continuous run | 31.6s |
| `/tmp/po-captures-1080p/shot-C-board.webm` (29.4s) | C (47.0–74.7s) | Production board and feed | 27.7s |
| `/tmp/po-captures-1080p/shot-D-interrupt.webm` (20.9s) | D (74.7–94.2s) | Technical proof expanded; immutable hash visible | 19.4s |
| `/tmp/po-captures-1080p/shot-E-reject.webm` (11.9s) | E (94.2–104.6s) | Reject path; zero plans applied | 10.5s |
| `/tmp/po-captures-1080p/shot-F-approve.webm` (11.9s) | F (104.6–115.0s) | Approval path; plan applied exactly once | 10.4s |
| Generated text card | A (0–15.5s) | Hero claim | 15.5s |
| Generated text card | G (115.0–149.4s) | Forged, valid, and replayed approval outcomes | 34.4s |
| Generated text card | H (149.4–167.4s) | Governance-layer close and repository URL | 17.9s |

## Rebuild

Start the local demo in one terminal:

```bash
uv sync --locked
uv run production-orchestrator-demo
```

Then capture, assemble, and verify:

```bash
python3 scripts/capture/capture-demo-shots.py
scripts/capture/assemble_submission_video.py
scripts/capture/verify_submission_video.py /tmp/po-video-final-v3
```

Expected verification output:

```text
VISUAL VERIFICATION PASSED: A/G/H text visible; B-F fill the frame
```

Copy a verified build to durable storage only after that command succeeds:

```bash
install -Dm644 /tmp/po-video-final-v3/submission-video.mp4 \
  ~/Documents/Github/notes/submission-assets/submission-video.mp4
mkdir -p ~/Documents/Github/notes/submission-assets/segments
cp /tmp/po-video-final-v3/seg-*.mp4 \
  ~/Documents/Github/notes/submission-assets/segments/
```

## Regression guards

Two metadata-valid visual failures occurred in v2, so width/height checks alone
are insufficient:

1. Playwright records CSS viewport pixels, not device-scale pixels. A 1920×1080
   viewport paired with `record_video_size=3840x2160` put the page in the
   upper-left quadrant and filled the remaining 75% with neutral gray. Capture
   now pairs a 1920×1080 viewport with an exactly matching video surface.
2. Supplying two separate `-vf` options caused FFmpeg's scaling filter to
   replace the title-card `drawtext` filter. Assembly now constructs exactly one
   filter chain per output, and card strings are passed through `textfile` with
   expansion disabled rather than fragile inline quoting.

3. The original E/F selectors matched explanatory text before the real controls,
   so both recordings remained in the pending revision-1 state. Capture now
   targets `button[data-decision="reject"]` and
   `button[data-decision="approve"]`, then fails unless the corresponding
   outcome card appears. D likewise fails unless the technical panel is open
   and its exact-hash element exists; the panel is anchored to the viewport so
   that evidence is actually recorded.

`scripts/capture/verify_submission_video.py` decodes real frames and fails if:

- A, G, or H lacks visible card text;
- B, C, D, E, or F contains more than 10% neutral-gray recorder padding; or
- any segment is not exactly 1920×1080.

## Pre-publish audit

- Re-read narration against `docs/ARCHITECTURE.md`; remove any unsupported claim.
- Keep numbers consistent across the video, Devpost copy, and builder.aws posts.
- Confirm no account IDs, ARNs, AWS profile names, credentials, or private paths
  appear in any frame.
- Extract one frame per shot directly from the concatenated MP4—not only from
  source segments—and compare A–H against `docs/VIDEO_SCRIPT.md` before upload.
- Upload to YouTube, then verify public logged-out playback at 1080p with audio.
