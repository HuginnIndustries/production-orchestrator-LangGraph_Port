# Submission video — shot-by-shot script

**Length:** approximately **3:59**, hard cap 5:00 (rules). **Language:** English. **Host:** public YouTube or Vimeo.
**Frame:** establish the problem, audience, hackathon, and stack; demonstrate the complete governed workflow; then prove the cloud deployment and close on the reusable governance product.

Every number spoken below is produced by a command or committed report in this repository; the "Proof" column names it. Deployment claims must remain aligned with [`ARCHITECTURE.md`](ARCHITECTURE.md) and the committed evidence reports.

The final cut uses narration-only presentation. Every non-code claim card is narrated; no on-camera appearance is required.

## Shot list

| # | Time | On screen | Narration (spoken) | Proof behind it |
|---|---|---|---|---|
| **A** | 0:00–0:45 | Two narrated 1080p slates: project/problem/audience/hackathon/track/stack, then the hero promise with forged/stale/replayed/restart refusals | "One wrong schedule update can make several customer orders late. Production Orchestrator helps small embroidery and decorated-apparel shops handle rush orders across machines, materials, schedules, and customer promises. It is for the shop owners, production managers, and operations teams responsible for those commitments. It is my Professional Agents entry for the Agents for Humans Hackathon, built with Strands Agents and deployed on Amazon Bedrock Agent Core. It works end to end, but its governing promise is zero unapproved writes. Human approval binds to the exact reviewed proposal. The exact approved plan applies once. Every other write fails closed, even across restarts and hostile inputs." | `scripts/capture/assets/intro-context.svg`; `intro-governance.svg`; Strands and AgentCore proof rows below |
| **B** | 0:45–1:17 | The customer-email card labelled **UNSTRUCTURED IN**; then the first feed row appears as the agent extracts and validates the request | "It starts where work actually starts — a customer email. Forty embroidered caps, Friday, gold thread. The model reads that email and proposes structured fields. It does not get to *assert* anything: the intake tool re-validates every field against the shop's catalog and calendar, then derives the duration and the thread quantity itself. A product that doesn't exist, a negative quantity, a day that isn't a work day — all rejected before anything is written. And this runs on Amazon Bedrock." | `tests/test_intake.py` (five fail-closed cases); `test_derivation_is_deterministic_and_whole_hours`; `evidence/bedrock-intake-rejection.json`; `evidence/bedrock-intake-approval.json` |
| **C** | 1:17–1:45 | Activity feed filling in: order queue, thread inventory, machine capacity, blockers, one coordinated plan, drafted messages. Cut to the **Production board** showing the conflict | "Now it works the shop through real tools — the order queue, thread inventory, machine capacity. Deterministic logic, not the model, finds the two blockers: the rush job collides with a machine that's already full on Friday, and there isn't enough red thread. It proposes one coordinated plan — move the lower-priority job, order the thread, tell the customer — and it drafts the messages. Every fact on this board came from a tool call." | Eight-tool trail in `evidence/*.json` `audit_event_types`; board rendered from the recorded run |
| **D** | 1:45–2:04 | Feed row **"Stopped at a real Strands interrupt"** / **"Holding the write for approval"**; expand **Technical proof** to show the full proposal hash, distinct process IDs, exact changes, and audit chain | "Then it stops. Not a confirmation dialog the agent could skip — a real Strands interrupt raised before the one tool that can change the shop. The plan is frozen as an immutable proposal, addressed by the hash of its own content. That hash is what you're about to approve, and it's the only thing that can be applied." | `ProductionPlanApprovalHook` on `BeforeToolCallEvent`; `test_start_prompt_binds_exact_persisted_proposal_hash` |
| **E** | 2:04–2:15 | Click **Keep current schedule**; outcome shows **Plan rejected**, revision 1, **Zero plans applied**, unchanged current plan, and unsent drafts | "Reject, and nothing moves. Revision one, zero plans applied, and the rejection itself is in the audit log. The agent doesn't get a second attempt at the same write." | Real run: `DECISION=reject`, `FINAL_STATE_REVISION=1`, `plan_applied_count` 0, `approval_rejected` in the audit chain |
| **F** | 2:15–2:25 | Reload, click **Approve coordinated plan**; outcome shows **Plan approved**, revision 2, **Applied the plan exactly once**, `RUSH-200` scheduled, `STANDARD-100` moved, and drafts unsent | "Approve, and exactly the plan you read gets applied — once. Revision two. The messages are still drafts; sending them is a separate decision a human still owns." | Real run: `FINAL_STATE_REVISION=2`, `plan_applied_count` 1; `test_exact_approval_atomically_applies_schedule_procurement_and_audit` |
| **G** | 2:25–3:00 | Full-screen proof card with three commands and outcomes: forged hash refused, legitimate approval succeeds, replay refused | "Here's the part that matters in production. The approval arrives in a *different process* — the worker restarted. So everything in that checkpoint is treated as hostile. Forge the proposal hash: refused — *checkpoint proposal does not match canonical persisted evidence*, exit one, no report written. Replay a real approval after the shop has moved: refused — *domain state changed after the interrupt checkpoint*. Wrong interrupt id, wrong session, altered provider binding, stale state — every one fails closed, and the attempt is recorded." | Verified runs, exit code 1 for forged hash and replay; plus `test_wrong_interrupt_id_fails_closed_after_restart`, `test_wrong_session_identity_fails_closed_after_restart`, `test_altered_provider_binding_fails_before_model_construction`, `test_stale_domain_state_fails_closed_after_restart`, `test_workflow_provider_rejects_forged_proposal_before_mutation` |
| **I** | 3:00–3:19 | Sanitized AgentCore proof card populated from committed evidence: deployed runtime and endpoint, reject/approve outcomes, distinct PIDs, proposal-hash prefix, and evidence path | "The same eight-tool workflow is deployed on Amazon Bedrock Agent Core. The runtime and endpoint are ready. Live start-and-resume invocations ran in separate processes: rejection applied zero plans, while approval applied the exact reviewed hash once. The evidence is committed in the repository." | `evidence/agentcore-invocation-evidence.json`; assembler refuses to render unless the evidence proves both outcomes, matching hashes, and real process boundaries |
| **H** | 3:19–3:59 | Governance architecture flow, then branded close with project, hackathon, track, hero claim, stack, evidence summary, and repository URL | "The scheduling is the demo. The governance layer is the product: one gated write, immutable proposals, approval bound to the exact reviewed hash, fail-closed restarts, and a complete audit chain. Its promise is zero unapproved writes. The same pattern applies anywhere an agent may read freely but write only what a human approved. All code, architecture, tests, and deployment evidence are public at GitHub dot com slash The American Maker slash production orchestrator. Production Orchestrator is my Professional Agents entry for Agents for Humans, built with Strands Agents and deployed on Amazon Bedrock Agent Core." | `docs/ARCHITECTURE.md`; `scripts/capture/assets/governance-architecture.svg`; `outro-title.svg` |

Scene ID `I` is intentionally inserted before the closing `H` so the established closing-shot identifier and narration filename remain stable.

## Appendix: staging the fail-closed capture (shot G)

Verified on `main` at `d8b7662`. Uses the deterministic workflow provider, so it needs no AWS credentials and costs nothing — the same code path the Bedrock runs take.

```bash
# 1. Reach a real interrupt and checkpoint it.
uv run python -m production_orchestrator.restart_spike start \
  --runtime-dir data/runtime/attack-demo \
  --checkpoint data/runtime/attack-demo/checkpoint.json \
  --provider deterministic-workflow --model deterministic-workflow-model \
  --scenario rush-order
# prints INTERRUPT_ID=… and PROPOSAL_HASH=…

# 2. Forge the proposal hash in the checkpoint, then try to approve.
cp -r data/runtime/attack-demo data/runtime/attack-forged
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("data/runtime/attack-forged/checkpoint.json")
c = json.loads(p.read_text()); c["proposal_hash"] = "f" * 64
p.write_text(json.dumps(c, indent=2))
PY
uv run python -m production_orchestrator.restart_spike resume \
  --runtime-dir data/runtime/attack-forged \
  --checkpoint data/runtime/attack-forged/checkpoint.json \
  --decision approve --report data/runtime/attack-forged/should-not-exist.json \
  --provider deterministic-workflow --model deterministic-workflow-model
# ValueError: Checkpoint proposal does not match canonical persisted evidence
# exit 1 — and should-not-exist.json is never created

# 3. Approve legitimately, then replay the same interrupt.
cp -r data/runtime/attack-demo data/runtime/attack-replay
uv run python -m production_orchestrator.restart_spike resume \
  --runtime-dir data/runtime/attack-replay \
  --checkpoint data/runtime/attack-replay/checkpoint.json \
  --decision approve --report data/runtime/attack-replay/approval.json \
  --provider deterministic-workflow --model deterministic-workflow-model
# FINAL_STATE_REVISION=2 / WORKFLOW_PASSED=true
uv run python -m production_orchestrator.restart_spike resume \
  --runtime-dir data/runtime/attack-replay \
  --checkpoint data/runtime/attack-replay/checkpoint.json \
  --decision approve --report data/runtime/attack-replay/replay.json \
  --provider deterministic-workflow --model deterministic-workflow-model
# ValueError: Domain state changed after the interrupt checkpoint — exit 1
```

Show the exit codes on camera (`echo "exit=$?"`); a stack trace alone reads as a crash, while a non-zero exit with no report written reads as a refusal. Runtime directories under `data/runtime/` are gitignored — delete them after capture.

## Recording notes

- **1920×1080, 30 fps minimum.** Browser at 100% zoom, window sized so the board and feed both fit without scrolling mid-shot.
- **Terminal:** light background, 16pt+, wide enough that no error line wraps. One command visible at a time.
- **Nothing sensitive on camera.** No AWS account ids, ARNs, profile names, access keys, real customer names, or personal paths. Prefer a clean shell in a plain directory; if a Bedrock shot is used, mask the account id in post.
- **Synthetic data only**, and say so on screen once (the demo header already carries `LOCAL · SYNTHETIC DATA`).
- Record narration separately from screen capture; the demo animations are short and easier to cut to a finished voice track.
- Keep the hero claim on screen as text at least twice (open and close) — judges skim.

## Pre-publish claims audit

Before upload, re-read the script against `ARCHITECTURE.md` and strike any sentence that:

1. states a capability without a matching proof row and committed report;
2. implies deployment, model access, or test results not backed by that report;
3. describes the demo's deterministic model as the judged provider, or vice versa;
4. says "secure" or "impossible" where the honest word is "fails closed."

The submission text, requirements matrix, and builder.aws posts must use the same numbers as the finished cut. Tracking: issue #13.
