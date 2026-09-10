# Builder Center publication source: post 1 of 3

> **Publisher:** Put the title value below in Builder Center's title field. Paste the article body starting after the `ARTICLE BODY START` marker. Do not paste this instruction, the title label, or the marker.

**Title field:** Hash-Bound Human Approval for Agent Writes - Agents for Humans

<!-- ARTICLE BODY START -->

Agents are getting good at *reading* systems: summarizing, planning, drafting. The harder problem is the write. One bad write can cost more than a string of useful recommendations: the wrong schedule disrupts production, and the wrong email damages a customer relationship.

For the [Agents for Humans](https://agentsforhumans.devpost.com/) hackathon we built [**Production Orchestrator**](https://devpost.com/software/production-orchestrator), a Strands Agents scheduling agent for small embroidery and decorated-apparel shops. The part worth writing about is not the scheduling. It is the gate around schedule and procurement changes: the agent can *propose* them but cannot *perform* them without a human decision bound to the exact bytes that the human reviewed.

## The pattern in one paragraph

The agent runs a real tool loop: read the order queue, check thread inventory, check machine capacity, find blockers, draft the plan and the customer/supplier messages. The trusted workflow start allows one narrow intake write: after deterministic validation, it adds the candidate order to the queue without changing the shop revision. The approval gate discussed here specifically controls the schedule and procurement changes in the plan. The final tool, `apply_production_plan`, is the only write for those changes. We wrap it with a Strands `BeforeToolCallEvent` hook that raises a real interrupt: the agent's turn ends, the plan is persisted as an immutable, hash-addressed proposal, and the workflow exits with the proposal hash on stdout. Nothing in the proposed schedule or procurement plan has changed yet. When the human decides, a **fresh process** restores the persisted Strands session, re-verifies the checkpoint, and submits the official `interruptResponse`. The reviewed plan is written exactly once, or not at all.

## Why hash-bound, not just human-in-the-loop

A "human approved this" flag is easy to forge and can become stale. The decision our resume phase accepts must name the proposal hash, that hash must still match canonical persisted evidence, and the current domain digest must still match the state recorded at interrupt time. Those layered proposal-binding and state-digest checks make three attacks fail closed, each covered by committed contract tests and shown in the recorded demo:

1. **Forged hash** - edit the checkpoint's `proposal_hash` to 64 zeros and approve: `ValueError: Checkpoint proposal does not match canonical persisted evidence`, exit 1, no report written, revision unchanged.
2. **Stale state** - mutate the shop database behind the checkpoint, then approve: `ValueError: Domain state changed after the interrupt checkpoint`. The digest recorded at interrupt time no longer describes reality.
3. **Replay** - submit the same approval twice: the second is refused, and the audit trail shows exactly one `plan_applied` event from the first accepted approval.

A human rejection enters the audit log with the proposal hash and reason. Integrity and checkpoint refusals take a different path: they exit nonzero before mutation and do not append a dedicated refusal event today. The contract tests back the public claim: unapproved schedule and procurement writes do not occur, and forged, stale, or replayed decisions are refused before another plan can be applied.

## What the journey actually looked like

Two defects we shipped and then caught are the honest part of this story:

- **The resume gate that gated nothing.** Our resume phase originally checked `provider == "bedrock"` with a literal string comparison. A live Bedrock evidence run revealed that a genuine `bedrock-workflow` checkpoint could never pass its own trusted-configuration check - the suite never exercised that path. The fix made a single `_provider_configuration()` helper the source of truth for provider identity across `agent_id_for()`, `start()`, and `resume()`, with a parametrized contract test over every provider.
- **The forged-hash window.** Early on, the resume path trusted the checkpoint's proposal hash without re-checking it against the canonical proposal persisted at interrupt time. After checkpoint tampering, Strands could resume and apply the genuine pending proposal even though the checkpoint named a different hash. That accepted an identity mismatch between the approval checkpoint and the proposal being resumed. The fix validates checkpoint identity against persisted evidence *before* the model is constructed, so the refusal happens before any write path exists.

Both were found by running the workflow against real Bedrock and attacking our own checkpoint files - the second finding became the on-camera attack demo.

## The numbers behind the claim

- 114 automated tests, ~85% coverage, and current main CI green; the fail-closed behaviors are contract tests, not manual checks
- The same scenario produces the **same canonical proposal hash** (`6ef62d9f…`) across three model backends: deterministic, Amazon Bedrock (Nova Lite), and a local Ollama model. The model extracts requested fields from the customer email; deterministic code validates those fields against the catalog and calendar, then derives duration and material quantities.
- Live Bedrock runs of the rejection and approval paths are committed as evidence reports: rejection holds revision 1 with zero applications; approval reaches revision 2 with exactly one

All shop, order, customer-email, and communication data shown in the project is synthetic.

## Why this generalizes

The scheduling domain is the demo; the reusable part is the governance layer. The same pattern applies whenever an agent needs to write to a system of record: immutable hash-addressed proposals, interrupts that end the agent's turn, decisions bound to reviewed content, and fail-closed verification across process death. Production Orchestrator builds that pattern from Strands SDK primitives.

The code is Apache-2.0 at [github.com/TheAmericanMaker/production-orchestrator](https://github.com/TheAmericanMaker/production-orchestrator), with committed contract tests, Bedrock evidence reports, AgentCore invocation evidence, and the full audit-chain design.

*This post is part of my entry in the Agents for Humans hackathon. Next: the implementation details that make approval restart-safe.*