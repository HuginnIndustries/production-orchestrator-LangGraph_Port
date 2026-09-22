# LangGraph port of the governed loop

This document places the two implementations of Production Orchestrator's governed agent loop side by side: the original Strands Agents implementation that was submitted to Agents for Humans, and a LangGraph `StateGraph` implementation added afterwards. The goal of the port is a single honest sentence:

> The same eight tools, the same guardrails, and the same restart-safe human approval, expressed as a LangGraph `StateGraph` with `interrupt()`.

Every claim below is backed by a test in `tests/test_langgraph_workflow.py`, `tests/test_evals.py`, or the golden set under `evals/`. Where the two paths are *not* identical, the difference is stated rather than smoothed over.

## What is shared

Both frameworks import the same deterministic modules and never reimplement them:

| Concern | Shared module | Used by |
|---|---|---|
| Tool names, descriptions, argument lists, ordering, catalog gating | `tool_specs.py` (`TOOL_SPECS`, `bind_shop_tools`) | `workflow.build_strands_tools` wraps each bound callable in `@tool`; `langgraph_workflow.build_langgraph_tools` wraps the same callables in `StructuredTool` |
| Shop reads, intake, blocker analysis, proposal creation, drafts, apply | `workflow.ShopService` | both |
| Intake validation (fail-closed) | `intake.validate_extraction` | both, via `ShopService.intake_customer_request` |
| Planner, canonical hash, drafts | `planning.py` | both |
| SQLite shop state, proposals, decisions, audit chain | `persistence.SQLiteShopRepository` | both — same `shop.db` schema, same audit event names |
| The one write, with hash / decision / rejection / staleness checks | `approval.apply_production_plan` | both — it is the only function that calls `apply_approved_plan` |
| Offline model behaviour (which tool next, arguments read from prior tool results) | `restart_spike.DeterministicWorkflowModel` (Strands) and `langgraph_workflow.DeterministicToolPlanner` (LangGraph) implement the same scripted sequence | see "What differs" |
| Synthetic scenarios and expected extractions | `fixtures.SCENARIOS` | both |

`tests/test_tool_specs.py` asserts the Strands surface is derived from `TOOL_SPECS` (same names, same order, intake only with a catalog, same parameter names and first-line descriptions). `test_langgraph_tools_match_strands_tool_surface` asserts the same for the LangGraph surface.

## Where the interrupt lives

| | Strands (`workflow.py`, `restart_spike.py`) | LangGraph (`langgraph_workflow.py`) |
|---|---|---|
| Mechanism | `ProductionPlanApprovalHook` registers on `BeforeToolCallEvent`; when the model calls `apply_production_plan`, the hook calls `event.interrupt("production-orchestrator-apply-plan", reason=summary)` | The `approval_gate` node calls `langgraph.types.interrupt(payload)` |
| What the human sees | `ShopService.proposal_summary(hash)` — id, hash, base revision, target, schedule changes, procurement | `{"name", "proposal_hash", "proposal": canonical JSON of the full proposal, "summary": same fields as the Strands summary}` |
| Who decides to reach the gate | The model: it must emit an `apply_production_plan` tool call, and the hook intercepts it | The graph: `plan → approval_gate` is a fixed edge. The planner is **forbidden** from calling `apply_production_plan` (`_run_phase` raises); the apply node is the only caller |
| Resume | `agent([{"interruptResponse": {"interruptId": …, "response": "y" | "n"}}])` | `graph.invoke(Command(resume={"approved", "actor", "reviewed_hash"}), config)` — a bare `"y"`/`"n"` string is also accepted and, like the Strands hook recording its configured actor, is attributed to the thread's bound actor (`test_string_resume_values_behave_like_strands_interrupt_response` covers `y`/`yes` → applied and `n`/other → rejected) |
| Rejection routing | The hook sets `event.cancel_tool`; the tool never runs; the model receives the cancellation and stops | Conditional edge `approval_gate → rejected` (terminal) when `decision.approved` is false; `apply` is never entered |
| Malformed decision | Anything other than an explicit yes is a rejection | Anything other than a mapping with a string `actor`, string `reviewed_hash`, and `approved is True` is a rejection (`_normalize_decision`, `test_malformed_resume_value_defaults_to_denial`) |
| Identity checked before the ledger write | The hook records `self.actor` from process configuration; a resume value cannot name an actor | The gate compares the decision's actor and the resuming process's binding with the thread's binding **before** `record_decision`; a mismatch is recorded as `approved=0` with the offending actor kept for audit. The `approval_decisions` table is shared with the Strands surface, so a foreign approval must never land there as `approved=1` (`test_wrong_actor_is_denied_at_the_gate_and_never_poisons_the_ledger`, `test_wrong_binding_is_denied_at_the_gate_and_never_poisons_the_ledger`, and the two CLI tests, which also assert `ShopService.apply_plan` cannot be driven off the ledger) |

The LangGraph version is strictly *more* structural about the gate: the Strands version relies on the model choosing to call the write tool (and on the hook catching it), while the graph reaches the gate by construction and refuses to let the model step call the write tool at all.

## Where integrity checks run

Both paths end in `approval.apply_production_plan`, which re-derives the hash from proposal content, requires a persisted decision bound to that exact hash, refuses rejections, and lets `apply_approved_plan` refuse a moved revision. On top of that:

| Check | Strands | LangGraph |
|---|---|---|
| Proposal hash matches content | `apply_production_plan` + `SQLiteShopRepository.load_proposal` integrity check | `_verify_and_apply` step 1: re-hash the proposal carried in thread state, then require it to equal the persisted proposal byte-for-byte; then `apply_production_plan` repeats it on the persisted copy |
| Shop revision unchanged | `apply_approved_plan` (`StaleStateError`), plus `restart_spike.resume` compares the domain digest at interrupt with the current digest before submitting the response | `_verify_and_apply` step 5: revision must equal both `proposal_revision` recorded in the thread and `proposal.base_revision`, and the domain digest must equal `proposal_digest` recorded when the plan was cut; `apply_approved_plan` then checks revision again |
| Approval not replayed | `test_resumed_interrupt_cannot_be_replayed` — a second `resume` against the same checkpoint fails; `apply_approved_plan` refuses after the revision moved | `resume()` refuses when `approval_gate` is no longer pending (`test_double_approve_on_same_thread_is_refused`); rewinding the thread to the gate checkpoint and replaying is refused because a `plan_applied` audit event already names the hash (`test_replayed_approval_after_apply_is_refused`) |
| Identity | `record_decision(actor=…)` records the operator; `restart_spike` binds session and agent identity into the checkpoint and verifies them on resume | `RuntimeBinding{actor, provider, model_id}` is stored in thread state at `start`; the gate denies before writing the ledger (row above), and `_verify_and_apply` step 2 re-checks as defence in depth. `apply_production_plan(expected_actor=…)` refuses a ledger row from any other actor (`tests/test_approval.py::test_approval_from_a_different_actor_is_denied_when_actor_is_expected`; `test_apply_node_still_refuses_a_foreign_ledger_approval` covers the graph side) |
| Provider binding | `_provider_configuration` persisted in the checkpoint and compared field-by-field at resume (provider, model, profile, region, credential source, Ollama host) | The same comparison on `provider` and `model_id`, at the gate and again in apply. There is no AWS profile / region / credential-source dimension because the LangGraph path has no cloud provider (see gaps) |
| Persisted decision is the one this thread made | n/a (single process records and applies in one hook) | `record_decision` returns the ledger row's `sequence`; the gate stores it in the thread's decision and `_verify_and_apply` step 4 requires `latest_decision(hash).sequence` to equal it — row identity, not value equality (`test_persisted_decision_mismatch_is_refused`, `test_decision_sequence_binds_apply_to_the_exact_ledger_row`) |
| Malformed thread proposal | n/a | A proposal payload that cannot be decoded is refused with an `apply_refused` audit event and the thread ends at `rejected` rather than wedging (`test_malformed_proposal_payload_in_thread_is_refused_with_audit`) |

On any failure the apply node records an `apply_refused` audit event, sets `outcome="refused"`, and routes to the terminal `rejected` node. `_assert_refused` in the tests verifies revision 1, no `plan_applied`, and `apply_refused` as the last event for every refusal case.

## Persistence across a process boundary

| | Strands | LangGraph |
|---|---|---|
| Durable store | `FileSessionManager` under `runtime/sessions/` + a hand-written `checkpoint.json` verified by `_load_checkpoint` | `SqliteSaver` in `runtime/langgraph_checkpoints.db` next to `runtime/shop.db`; thread state (request, tool-call history, proposal, hash, revision, digest, binding, decision, outcome) is the checkpoint |
| Fresh-process resume | `production-orchestrator-restart-spike resume` reconstructs the agent and session and submits the official `interruptResponse` | `production-orchestrator-langgraph-demo decide --thread <id>` builds a `GraphRuntime` **without a planner**, calls `pending_interrupt()` (reads the interrupt from the checkpointed task), and resumes with `Command(resume=…)` |
| Proof | `tests/test_restart_spike.py` | `test_fresh_process_resumes_langgraph_interrupt[--reject/--approve]` (subprocess `start`, subprocess `decide`, distinct pids), `test_fresh_runtime_sees_pending_interrupt_and_resumes` |

## Graph shape

```
START → intake → analyze → plan → approval_gate ─┬─ approved ──→ apply ─┬─ applied → done → END
                                                 └─ rejected ──→ rejected ← refused ┘
```

- `intake`: `intake_customer_request` (the one sanctioned pre-proposal write; revision unchanged).
- `analyze`: `list_active_orders`, `get_inventory`, `get_machine_capacity`, `analyze_shop_blockers`.
- `plan`: `propose_schedule`, `draft_communications`; records proposal, hash, base revision, and domain digest in state and re-hashes the proposal before the gate.
- `approval_gate`: `interrupt()`; records the decision against the exact hash.
- `apply`: `_verify_and_apply`; the only node that can mutate the shop.
- `rejected` / `done`: terminal.

State is a `TypedDict` (`OrchestratorState`) with `tool_calls` as an `operator.add` reducer so history accumulates across nodes and survives checkpointing.

## Eval framework

`evals/run_evals.py` runs each `evals/cases/*.json` case through both paths offline and asserts the same proposal hash, tool sequence, audit chain, final revision, and outcome (`expects: "proposal"` cases), or the same fail-closed invariants — no proposal, revision 1, nothing applied (`expects: "fail_closed"` cases). It prints a markdown table and exits non-zero on any mismatch; `tests/test_evals.py` runs it in the suite and also proves the non-zero exit with a tampered case. CI runs `uv run python evals/run_evals.py` after the test suite.

The 13 committed cases: 10 full-parity cases across all three scenarios with both verdicts and quantity/priority/day variants that produce distinct hashes, plus 3 fail-closed cases (an infeasible batch the planner refuses, two invalid intakes). The summary line reports the two groups separately; the task spec asked for tool-sequence agreement on every case, and for the 3 fail-closed cases that is deliberately **not** asserted (gap 4).

## Known gaps and honest differences

1. **No live model on the LangGraph path.** Only `DeterministicToolPlanner` exists. The Strands path has Bedrock, Ollama, and deterministic providers; the LangGraph path has one. A live planner would implement `ToolPlanner.next_call`; none is written or tested, and no provider SDK is a dependency.
2. **Intake extraction is scripted, not modelled.** The eval cases carry the structured `extraction` the offline model "produces"; the customer email is context, not input to any NLP. This matches how the Strands offline demo works, but it means the evals do not test extraction quality on either path.
3. **Provider binding is narrower.** The LangGraph binding compares actor, provider, and model id. It has no AWS profile, region, credential-source, or Ollama-host fields because nothing on this path uses them.
4. **Fail-closed tool trails differ.** When intake or planning raises, the scripted Strands model keeps calling read tools after the failed tool (six tool calls, no proposal), while a LangGraph node halts at the first exception (zero recorded calls, no proposal). Both refuse without a proposal or a write; the eval compares only those invariants for `fail_closed` cases (3 of 13) and says so in the code and in its summary line. This is a deviation from the spec's "same tool-call sequence" criterion for those cases.
5. **Interrupt payload shape differs.** LangGraph's payload carries the canonical proposal JSON in addition to the summary; Strands carries only the summary. Both bind the same hash.
6. **Replay protection is checkpoint-shaped.** In LangGraph a thread can be rewound to the gate checkpoint with `get_state_history`; the apply node refuses that replay via the `plan_applied` audit record, not via the checkpointer. This is tested, but it is a different mechanism from Strands' one-shot `interruptResponse`.
7. **No AgentCore wrapper.** `agentcore_app.py` is untouched and Strands-only; there is no deployment path for the LangGraph graph.
8. **No web demo.** The LangGraph path has the two-phase CLI only; the judge-facing HTTP demo remains Strands-only.
9. **Not exercised against a real network provider.** Everything here runs offline by design of the task; nothing was executed on Bedrock or Ollama for the LangGraph path.
10. **Single writer per runtime directory.** The `SqliteSaver` connection uses a 30 s busy timeout; two `decide` processes racing on the same thread are serialised by SQLite, and the loser then finds no pending interrupt. Concurrent decides are not tested.
11. **Actor and binding are configuration, not authentication.** Like the Strands hook's configured actor and AWS profile, `RuntimeBinding` is trusted process configuration. The checkpoint DB and CLI flags are inside the trust boundary; with write access to the runtime directory an operator can rebind a thread and resume it. The checks catch a resume from the wrong process or a misconfigured operator, not a hostile one.
12. **Shared ledger, different consumers.** `approval_decisions` in `shop.db` is read by both frameworks. The LangGraph gate never writes an `approved=1` row for a foreign actor or process, and `apply_production_plan` can be told the expected actor; the pre-existing Strands callers (`ShopService.apply_plan`, `agentcore_app.py`) do not pass one and were left unchanged. When an entitled approval's apply is refused (stale digest, tampered thread), the graph records a superseding `Voided` denial under the system actor `langgraph-apply` (original approver kept in the reason) so the hash's latest decision is no longer approved (`test_refused_apply_voids_the_ledger_approval_for_other_consumers`); tampered gate inputs (malformed binding, missing hash) are denied with an audit event rather than raising and wedging the thread (`test_tampered_gate_inputs_are_denied_with_audit_not_wedged`).

## Commands

```bash
uv run production-orchestrator-langgraph-demo start --runtime-dir data/lg/run1 --scenario rush-order
uv run production-orchestrator-langgraph-demo decide --runtime-dir data/lg/run1 --thread <THREAD_ID> --approve
uv run python evals/run_evals.py
uv run pytest tests/test_langgraph_workflow.py tests/test_evals.py tests/test_tool_specs.py
```
