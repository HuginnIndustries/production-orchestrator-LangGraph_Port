# Video assembly inventory — Production Orchestrator submission

Generated Sep 8, 2026. All screen material for shots A–F + X is captured; shot G
is scripted and verified. Waiting on: narration audio (Breeze-TTS-2 clips from
mimir, due Sep 9 midday) and final voice selection.

## Captured footage (1920×1080, ~30fps, MP4)

| File | Shot | Content | Duration target |
|---|---|---|---|
| `/tmp/po-captures/shot-X-chips.mp4` | X (insert) | scenario chips: rush order / team jerseys / metallic monogram | 5s |
| `/tmp/po-captures/shot-B-intake.mp4` | B (0:22–0:55) | intake email card → feed rows as agent extracts + validates | 33s |
| `/tmp/po-captures/shot-C-board.mp4` | C (0:55–1:45) | feed filling: orders/inventory/capacity/blockers/plan/drafts + production board conflict | 50s |
| `/tmp/po-captures/shot-D-interrupt.mp4` | D (1:45–2:15) | interrupt row + Technical proof expansion (proposal hash) | 30s |
| `/tmp/po-captures/shot-E-reject.mp4` | E (2:15–2:40) | Keep current schedule → board unchanged, zero plans applied | 25s |
| `/tmp/po-captures/shot-F-approve.mp4` | F (2:40–3:05) | Approve coordinated plan → board animates, applied exactly once | 25s |

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