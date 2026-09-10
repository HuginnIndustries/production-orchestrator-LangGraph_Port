# Video assembly inventory — Production Orchestrator submission

Updated September 9, 2026. This document describes the enhanced v5 submission
pipeline. It supersedes the 2:47 v3 cut while preserving its semantically
verified B–G demonstration footage.

## Final artifact contract

- Durable video: `~/Documents/Github/notes/submission-assets/submission-video.mp4`
- Durable segments: `~/Documents/Github/notes/submission-assets/segments/`
  (`seg-A.mp4` through `seg-I.mp4`; presentation order is A–G, I, H)
- Scratch build: `/tmp/po-video-final-v5/`
- Review output: `/tmp/po-final-v5-review/contact-sheet-from-final-video.png`
- Format: H.264 video, AAC audio, 1920×1080, 30 fps, SAR 1:1, DAR 16:9
- Runtime: approximately 239.13 seconds (3:59); below the five-minute limit
- Existing narration: `~/po-narration-kokoro/shot-B.mp3` through `shot-G.mp3`
- New narration: `~/po-narration-kokoro-v2/shot-A-intro.mp3`,
  `shot-I-agentcore.mp3`, and `shot-H-outro.mp3`
- Voice: Kokoro `af_heart`, checked by local speech recognition before assembly

Video binaries stay outside Git. The repository contains the reproducible
capture, SVG card sources, assembly script, and visual verifier.

## Shot inventory

| Source | Shot and final range | Required state | Narration |
|---|---|---|---:|
| `assets/intro-context.svg`, `assets/intro-governance.svg` | A (0:00–0:45) | Project, problem, audience, hackathon, track, stack, then zero-unapproved-writes promise | 45.5s |
| `/tmp/po-captures-1080p/shot-B-intake.webm` | B (0:45–1:17) | Rush-order email and populated activity/tool trail | 31.6s |
| `/tmp/po-captures-1080p/shot-C-board.webm` | C (1:17–1:45) | Production-board conflict and coordinated proposal | 27.7s |
| `/tmp/po-captures-1080p/shot-D-interrupt.webm` | D (1:45–2:04) | Technical Proof expanded; proposal hash, process boundary, exact changes, and audit evidence visible | 19.4s |
| `/tmp/po-captures-1080p/shot-E-reject.webm` | E (2:04–2:15) | Rejected, revision 1, zero plans applied, unchanged schedule, drafts unsent | 10.5s |
| `/tmp/po-captures-1080p/shot-F-approve.webm` | F (2:15–2:25) | Approved, revision 2, exact plan applied once, RUSH-200 scheduled, STANDARD-100 moved, drafts unsent | 10.4s |
| Generated proof card | G (2:25–3:00) | Forged refusal, legitimate approval, and replay refusal | 34.4s |
| `assets/agentcore-proof.svg` populated from committed evidence | I (3:00–3:19) | Deployed runtime/endpoint, reject 0, approve 1, matching hash, distinct PIDs | 19.4s |
| `assets/governance-architecture.svg`, `assets/outro-title.svg` | H (3:19–3:59) | Governance flow, hero claim, hackathon identity, stack, evidence summary, repository URL | 40.1s |

Scene ID `I` is inserted before the established closing scene `H`; the file
names remain stable while presentation order follows the script.

## Rebuild

Prerequisites beyond the Python project are FFmpeg and Inkscape. Inkscape
renders the committed SVG sources into the final 1920×1080 raster before video
encoding.

Start the local demo in one terminal when the browser footage must be recaptured:

```bash
uv sync --locked
uv run production-orchestrator-demo
```

Then capture if needed, assemble, and verify:

```bash
python3 scripts/capture/capture-demo-shots.py
scripts/capture/assemble_submission_video.py
scripts/capture/verify_submission_video.py /tmp/po-video-final-v5
```

Expected verification output:

```text
VISUAL VERIFICATION PASSED: A/G/H/I text visible; B-F fill the frame
```

The assembler reads `evidence/agentcore-invocation-evidence.json` and refuses
to render the AgentCore card unless the committed data proves:

- reject and approve report `workflow_passed=true`;
- both runs prove a real process boundary;
- rejection applied zero plans;
- approval applied exactly one plan; and
- both decisions use the same canonical proposal hash.

Only sanitized runtime/endpoint names, result fields, PIDs, a short hash prefix,
and the repository-relative evidence path reach the frame. Account IDs, ARNs,
profiles, and session IDs are excluded.

The SVG scenes use FFmpeg's still-image `-loop 1` input mode. Stateful browser
captures are never filled with `-stream_loop`; each is one continuous recording
held for at least its narration duration.

## Durable installation

Copy a build only after automated and direct-final semantic review pass:

```bash
install -Dm644 /tmp/po-video-final-v5/submission-video.mp4 \
  ~/Documents/Github/notes/submission-assets/submission-video.mp4
mkdir -p ~/Documents/Github/notes/submission-assets/segments
cp /tmp/po-video-final-v5/seg-*.mp4 \
  ~/Documents/Github/notes/submission-assets/segments/
```

Compare source and destination SHA-256 hashes after copying. Archive the prior
video with `do-not-upload` in its filename before replacing the durable path.

## Regression guards

Metadata alone is insufficient; earlier valid-looking files contained visible
failures:

1. Playwright records CSS viewport pixels, not device-scale pixels. A 1920×1080
   viewport paired with `record_video_size=3840x2160` put the page in the
   upper-left quadrant and filled the remaining 75% with neutral gray. Capture
   now pairs a 1920×1080 viewport with an exactly matching recording surface.
2. Multiple `-vf` options allowed a later scale filter to replace title-card
   text. Each output now receives one explicit filter graph; complex card text
   uses files with expansion disabled, while the new presentation cards render
   from committed SVG sources.
3. Broad E/F text selectors matched explanatory copy rather than decision
   buttons, leaving both shots pending. Capture now targets
   `button[data-decision="reject"]` and
   `button[data-decision="approve"]`, then waits for exact outcome text.
4. An expanded D panel can still leave evidence below the viewport. Capture
   targets `details.technical > summary`, waits for the open state, and scrolls
   the hash/evidence region into view.
5. The first architecture probe masked the lower-row arrows behind component
   boxes. The corrected SVG connects human decision → fresh process → apply
   once → audit chain in visible gaps.

`scripts/capture/verify_submission_video.py` decodes actual frames and fails if:

- A, G, H, or I lacks visible card text;
- B, C, D, E, or F contains more than 10% neutral-gray recorder padding;
- any expected segment is missing; or
- any segment is not exactly 1920×1080.

## Direct-final semantic acceptance

After every rebuild, extract representative frames from the exact concatenated
`submission-video.mp4`, not from source segments. Include both visual phases of
A and H plus one frame each for B–G and I. Compare them against
`docs/VIDEO_SCRIPT.md` and confirm the decisive text at full resolution when a
contact-sheet thumbnail is too small.

Also inspect frames immediately before and after the A and H scene switches so
no blank transition is hidden by representative mid-scene frames. Confirm
narration is present near the opening, browser demonstration, attack proof,
AgentCore proof, and closing slate; compare audio/video durations numerically.

## Pre-publish audit

- Re-read narration against `docs/ARCHITECTURE.md`; remove any unsupported claim.
- Keep numbers consistent across the video, Devpost copy, and builder.aws posts.
- Confirm no account IDs, ARNs, AWS profile names, credentials, private paths,
  or session IDs appear in any frame.
- Preserve one authoritative contact sheet derived from the exact durable MP4.
- Upload to YouTube or Vimeo, then verify public logged-out playback at 1080p
  with audio.
