# Video assembly inventory — Production Orchestrator submission

Generated Sep 8, 2026. All screen material for shots A–F + X is captured; shot G
is scripted and verified. Waiting on: narration audio (Breeze-TTS-2 clips from
mimir, due Sep 9 midday) and final voice selection.

## Captured footage (v2, September 9 — supersedes the v1 table)

| File | Shot | Content | Narration |
|---|---|---|---|
| `/tmp/po-captures-4k/shot-B-intake.webm` (33.3s) | B (15.5–47.0s) | intake card + feed, one continuous run | 31.6s |
| `/tmp/po-captures-4k/shot-C-board.webm` (29.4s) | C (47.0–74.7s) | board + feed, continuous | 27.7s |
| `/tmp/po-captures-4k/shot-D-interrupt.webm` (21.0s) | D (74.7–94.2s) | technical proof expanded, hash visible | 19.4s |
| `/tmp/po-captures-4k/shot-E-reject.webm` (11.9s) | E (94.2–104.6s) | reject: zero plans applied | 10.5s |
| `/tmp/po-captures-4k/shot-F-approve.webm` (11.9s) | F (104.6–115.0s) | approve: applied exactly once | 10.4s |
| generated cards (A/G/H) | A (0–15.5s), G (115.0–149.4s), H (149.4–167.3s) | 4K text cards, **narrated** | 15.5 / 34.4 / 17.9s |

All sources 3840×2160 (device_scale_factor=2), assembled to 1920×1080 via
Lanczos + unsharp at 14 Mbps. **Final video:**
`~/Documents/Github/notes/submission-assets/submission-video.mp4` (167.4s ≈ 2:47,
11.2 MB) with per-segment files under `segments/`. Build tooling committed at
`0b220e6`: `scripts/capture/capture-demo-shots.py` +
`scripts/capture/assemble_submission_video.py`.

## Shot A (slate) and shot H (architecture close)

- A: hero-claim text card over a clean background — generate as a 22s static/animated
  card in the editor (no capture needed; text: "Zero unapproved writes — provably
  fail-closed under forged, stale, and replayed inputs, across a real process boundary.")
- H: architecture diagram from `docs/ARCHITECTURE.md` + hero-claim card. Render the
  diagram to PNG for the closing card.
- Pending insert between G and H (script says: only if the runtime is under target —
  **it is deployed and evidenced**): 15s AgentCore console/CLI shot — the
  `get-agent-runtime` READY output plus the invocation evidence JSON makes an
  honest terminal shot. Narration: "and it runs deployed, not just locally."

## Shot G — terminal attacks (scripted, verified)

- Script: `/tmp/po_shotG_record.sh` (run on camera; ~40s runtime)
- Verified outputs: forged → exit 1; legitimate → exit 0 (rev 2, passed); replay →
  exit 1; both attack reports never created
- Show `echo "exit=$?"` after each — the script includes it
- Runtime staging lives in `/tmp/po-attack-demo-g/` (gitignored-style scratch; delete after)

## Narration

- Script: `docs/VIDEO_SCRIPT.md` — shots A–H "Narration (spoken)" column, shot B
  INCLUDING the six added words ("…and this runs on Amazon Bedrock") since #11's
  evidence is committed
- Breeze clips expected: `~/po-narration/shot-<A..H>.mp3` (mimir agent delivering)
- Fallback: built-in TTS (rejected once — hold only if Breeze fails)

## Assembly steps (once audio lands)

1. Cut each capture to its narration length (durations above); speed 1.0
2. Lay narration track; sync cut points to the spoken beats
3. Shot A slate (0:00–0:22), X insert only if runtime is over (it isn't — skip or use as b-roll)
4. Shot G: record terminal per script; mask nothing (no account ids appear — ARNs
   are not printed by these commands)
5. H: architecture PNG + hero-claim card
6. 1920×1080, 30fps, target 4:00, hard cap 5:00; hero claim on screen at open and close
7. Export H.264 + AAC, upload public YouTube, verify logged-out playback

## Pre-publish audit (from VIDEO_SCRIPT.md)

- Re-read narration against `ARCHITECTURE.md` proof table; strike any pending-capability sentence
- Same numbers in video, Devpost copy, and the three builder.aws posts
- Verify: no account ids, no ARNs, no profile names, no real paths on camera