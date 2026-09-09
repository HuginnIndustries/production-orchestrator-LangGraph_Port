#!/usr/bin/env bash
# Shot G recording script — the attack-fails-closed segment for the video.
# Runs on camera (or under a terminal recorder): three commands, exit codes shown.
# Staging already done and verified (Sep 8):
#   /tmp/po-attack-demo-g/demo    — fresh interrupt checkpoint, hash 6ef62d9f…
#   /tmp/po-attack-demo-g/forged  — copy with proposal_hash = f*64
#   /tmp/po-attack-demo-g/replay  — legitimately approved (rev 2, applied once), replay.json refused
set -u
cd ~/Documents/Github/owned/TheAmericanMaker/production-orchestrator
PY=$(pwd)/.venv/bin/python
RUN=/tmp/po-attack-demo-g

echo "== Attack 1: forged proposal hash (checkpoint edited to f*64) =="
$PY -m production_orchestrator.restart_spike resume \
  --runtime-dir "$RUN/forged" --checkpoint "$RUN/forged/checkpoint.json" \
  --decision approve --report "$RUN/forged/should-not-exist.json" \
  --provider deterministic-workflow --model deterministic-workflow-model
echo "exit=$?"   # 1 — refused, no report written

echo
echo "== Attack 2: legitimate approval (baseline for the replay attack) =="
cp -r "$RUN/demo" "$RUN/replay-live"
$PY -m production_orchestrator.restart_spike resume \
  --runtime-dir "$RUN/replay-live" --checkpoint "$RUN/replay-live/checkpoint.json" \
  --decision approve --report "$RUN/replay-live/approval.json" \
  --provider deterministic-workflow --model deterministic-workflow-model
echo "exit=$?"   # 0 — FINAL_STATE_REVISION=2, WORKFLOW_PASSED=true

echo
echo "== Attack 3: replay the same approval after the shop moved =="
$PY -m production_orchestrator.restart_spike resume \
  --runtime-dir "$RUN/replay-live" --checkpoint "$RUN/replay-live/checkpoint.json" \
  --decision approve --report "$RUN/replay-live/replay.json" \
  --provider deterministic-workflow --model deterministic-workflow-model
echo "exit=$?"   # 1 — refused: domain state changed after the interrupt checkpoint

echo
ls "$RUN/forged/should-not-exist.json" 2>&1 | head -1   # No such file — nothing written
ls "$RUN/replay-live/replay.json" 2>&1 | head -1        # No such file — nothing written