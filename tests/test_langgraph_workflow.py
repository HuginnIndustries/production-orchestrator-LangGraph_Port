import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from langgraph.types import Command

from production_orchestrator.fixtures import SCENARIOS
from production_orchestrator.langgraph_workflow import (
    INTERRUPT_NAME,
    LANGGRAPH_MODEL_ID,
    LANGGRAPH_PROVIDER,
    ApplyRefused,
    DeterministicToolPlanner,
    GraphRuntime,
    build_langgraph_tools,
    canonical_proposal_json,
    planner_for_scenario,
)
from production_orchestrator.persistence import SQLiteShopRepository
from production_orchestrator.tool_specs import TOOL_NAMES
from production_orchestrator.workflow import ShopService

ACTOR = "test-operator"
BINDING = {"actor": ACTOR, "provider": LANGGRAPH_PROVIDER, "model_id": LANGGRAPH_MODEL_ID}
PENDING_EVENTS = [
    "scenario_initialized",
    "request_intake",
    "active_orders_read",
    "inventory_read",
    "machine_capacity_read",
    "blockers_analyzed",
    "proposal_created",
    "communications_drafted",
]


@pytest.fixture
def runtime(tmp_path: Path):
    instance = GraphRuntime(tmp_path, BINDING, planner=planner_for_scenario("rush-order"))
    yield instance
    instance.close()


def _fresh(tmp_path: Path, binding: dict | None = None) -> GraphRuntime:
    """A second process's view: same runtime dir, no planner, reloaded from SQLite."""
    return GraphRuntime(tmp_path, binding or BINDING)


def _events(runtime: GraphRuntime) -> list[str]:
    return [event.event_type for event in runtime.repository.audit_events()]


def _start(runtime: GraphRuntime, scenario: str = "rush-order") -> tuple[str, dict]:
    started = runtime.start(scenario)
    return started["thread_id"], started["interrupt"]


# --------------------------------------------------------------------------- tool surface


def test_langgraph_tools_match_strands_tool_surface(tmp_path: Path) -> None:
    spec = SCENARIOS["rush-order"]
    repository = SQLiteShopRepository(tmp_path / "shop.db", clock=lambda: "t")
    repository.initialize(spec.build())
    tools = build_langgraph_tools(ShopService(repository, catalog=spec.catalog))

    assert tuple(tools) == TOOL_NAMES
    assert set(tools["intake_customer_request"].args) == {
        "order_id",
        "product_code",
        "quantity",
        "requested_day",
        "priority",
    }
    assert tools["apply_production_plan"].args == {
        "proposal_hash": {
            "title": "Proposal Hash",
            "type": "string",
            "description": "Immutable hash returned by propose_schedule.",
        }
    }


def test_langgraph_tools_omit_intake_without_catalog(tmp_path: Path) -> None:
    repository = SQLiteShopRepository(tmp_path / "shop.db", clock=lambda: "t")
    repository.initialize(SCENARIOS["rush-order"].build())
    assert tuple(build_langgraph_tools(ShopService(repository))) == TOOL_NAMES[1:]


def test_planner_never_schedules_apply_and_reads_hash_from_tool_result() -> None:
    planner = planner_for_scenario("rush-order")
    state = {"target_order_id": "RUSH-200", "tool_calls": []}
    assert planner.next_call("intake", state).name == "intake_customer_request"
    with pytest.raises(RuntimeError, match="not available"):
        planner.next_call(
            "plan",
            {**state, "tool_calls": [{"name": "propose_schedule", "arguments": {}, "result": {}}]},
        )
    assert planner.next_call("plan", {**state, "tool_calls": []}).name == "propose_schedule"


def test_planner_requires_a_scenario_with_an_extraction() -> None:
    with pytest.raises(KeyError):
        planner_for_scenario("nope")
    assert isinstance(planner_for_scenario("team-jerseys"), DeterministicToolPlanner)


# --------------------------------------------------------------------------- happy paths


def test_start_stops_at_interrupt_with_canonical_proposal_and_hash(runtime: GraphRuntime) -> None:
    thread_id, payload = _start(runtime)

    state = runtime.state(thread_id)
    assert payload["name"] == INTERRUPT_NAME
    assert payload["proposal_hash"] == state["proposal_hash"]
    assert payload["proposal"] == canonical_proposal_json(state["proposal"])
    assert json.loads(payload["proposal"])["content_hash"] == payload["proposal_hash"]
    assert payload["summary"]["proposal_hash"] == payload["proposal_hash"]
    assert [call["name"] for call in state["tool_calls"]] == list(TOOL_NAMES[:-1])
    assert state["proposal_revision"] == 1
    assert state["decision"] is None
    assert state["outcome"] is None
    assert runtime.repository.load_state().revision == 1
    assert _events(runtime) == PENDING_EVENTS
    assert runtime.pending_interrupt(thread_id) == payload


def test_approve_applies_exactly_once_and_advances_revision(runtime: GraphRuntime) -> None:
    thread_id, payload = _start(runtime)

    result = runtime.resume(thread_id, approved=True)

    assert result["outcome"] == "applied"
    assert result["applied_revision"] == 2
    assert result["decision"]["reviewed_hash"] == payload["proposal_hash"]
    assert runtime.repository.load_state().revision == 2
    assert _events(runtime) == [*PENDING_EVENTS, "approval_granted", "plan_applied"]
    assert _events(runtime).count("plan_applied") == 1
    assert runtime.pending_interrupt(thread_id) is None


def test_reject_routes_to_rejected_without_touching_apply(runtime: GraphRuntime) -> None:
    thread_id, _ = _start(runtime)
    before = runtime.repository.domain_digest()

    result = runtime.resume(thread_id, approved=False)

    assert result["outcome"] == "rejected"
    assert result["applied_revision"] is None
    assert runtime.repository.load_state().revision == 1
    assert runtime.repository.domain_digest() == before
    assert _events(runtime) == [*PENDING_EVENTS, "approval_rejected"]
    assert "plan_applied" not in _events(runtime)


def test_drafts_remain_unsent_on_both_paths(runtime: GraphRuntime) -> None:
    thread_id, _ = _start(runtime)
    drafts = next(
        call["result"]["drafts"]
        for call in runtime.state(thread_id)["tool_calls"]
        if call["name"] == "draft_communications"
    )
    assert {draft["audience"] for draft in drafts} == {"customer", "operator", "supplier"}
    runtime.resume(thread_id, approved=False)
    assert not [event for event in _events(runtime) if "sent" in event]


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_every_scenario_reaches_interrupt_and_applies(tmp_path: Path, scenario: str) -> None:
    runtime = GraphRuntime(tmp_path, BINDING, planner=planner_for_scenario(scenario))
    try:
        thread_id, payload = _start(runtime, scenario)
        assert runtime.repository.load_proposal(payload["proposal_hash"]) is not None
        assert runtime.resume(thread_id, approved=True)["outcome"] == "applied"
        assert runtime.repository.load_state().revision == 2
    finally:
        runtime.close()


def test_string_resume_values_are_accepted_like_strands(runtime: GraphRuntime) -> None:
    thread_id, _ = _start(runtime)
    result = runtime.graph.invoke(
        Command(resume="n"),
        runtime.config(thread_id),
    )
    assert result["outcome"] == "rejected"
    assert result["decision"]["actor"] == "unknown"


# --------------------------------------------------------------------------- persistence


def test_fresh_runtime_sees_pending_interrupt_and_resumes(tmp_path: Path) -> None:
    first = GraphRuntime(tmp_path, BINDING, planner=planner_for_scenario("rush-order"))
    thread_id, payload = _start(first)
    first.close()

    second = _fresh(tmp_path)
    try:
        assert second.planner is None
        assert second.pending_interrupt(thread_id) == payload
        result = second.resume(thread_id, approved=True)
        assert result["outcome"] == "applied"
        assert second.repository.load_state().revision == 2
    finally:
        second.close()


def test_checkpoint_db_lives_next_to_shop_db(runtime: GraphRuntime, tmp_path: Path) -> None:
    _start(runtime)
    assert (tmp_path / "shop.db").is_file()
    assert (tmp_path / "langgraph_checkpoints.db").is_file()
    with sqlite3.connect(tmp_path / "langgraph_checkpoints.db") as connection:
        assert connection.execute("select count(*) from checkpoints").fetchone()[0] > 0


def test_unknown_thread_has_no_pending_interrupt(runtime: GraphRuntime) -> None:
    assert runtime.pending_interrupt("never-started") is None
    with pytest.raises(ApplyRefused, match="no pending"):
        runtime.resume("never-started", approved=True)


def test_resume_without_planner_cannot_start(tmp_path: Path) -> None:
    runtime = _fresh(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="planner"):
            runtime.start("rush-order")
    finally:
        runtime.close()


def test_start_rejects_unknown_scenario(runtime: GraphRuntime) -> None:
    with pytest.raises(ValueError, match="Invalid scenario"):
        runtime.start("not-a-scenario")


# --------------------------------------------------------------------------- fresh-process resume


def _cli(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "production_orchestrator.langgraph_demo", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _cli_start(runtime_dir: Path, *extra: str) -> dict[str, str]:
    result = _cli("start", "--runtime-dir", str(runtime_dir), *extra)
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


@pytest.mark.parametrize(
    ("flag", "expected_revision", "expected_applied", "expected_outcome"),
    [("--reject", 1, 0, "rejected"), ("--approve", 2, 1, "applied")],
)
def test_fresh_process_resumes_langgraph_interrupt(
    tmp_path: Path,
    flag: str,
    expected_revision: int,
    expected_applied: int,
    expected_outcome: str,
) -> None:
    started = _cli_start(tmp_path, "--scenario", "metallic-monogram")
    assert started["TOOL_CALLS"].split(",") == list(TOOL_NAMES[:-1])
    assert json.loads(started["PROPOSAL"])["content_hash"] == started["PROPOSAL_HASH"]
    report_path = tmp_path / "report.json"

    _cli(
        "decide",
        "--runtime-dir",
        str(tmp_path),
        "--thread",
        started["THREAD_ID"],
        flag,
        "--report",
        str(report_path),
    )

    report = json.loads(report_path.read_text())
    assert report["outcome"] == expected_outcome
    assert report["proposal_hash"] == started["PROPOSAL_HASH"]
    assert report["final_state_revision"] == expected_revision
    assert report["plan_applied_count"] == expected_applied
    assert isinstance(report["resume_process_id"], int)
    assert report["resume_process_id"] != os.getpid()
    expected_events = PENDING_EVENTS + (
        ["approval_granted", "plan_applied"] if flag == "--approve" else ["approval_rejected"]
    )
    assert report["audit_event_types"] == expected_events


def test_cli_double_decide_is_refused(tmp_path: Path) -> None:
    started = _cli_start(tmp_path)
    _cli("decide", "--runtime-dir", str(tmp_path), "--thread", started["THREAD_ID"], "--approve")

    second = _cli(
        "decide",
        "--runtime-dir",
        str(tmp_path),
        "--thread",
        started["THREAD_ID"],
        "--approve",
        check=False,
    )

    assert second.returncode == 2
    assert "no pending approval interrupt" in second.stderr
    repository = SQLiteShopRepository(tmp_path / "shop.db", clock=lambda: "t")
    assert repository.load_state().revision == 2
    assert [e.event_type for e in repository.audit_events()].count("plan_applied") == 1


def test_cli_refuses_a_swapped_actor_before_mutation(tmp_path: Path) -> None:
    started = _cli_start(tmp_path)
    result = _cli(
        "decide",
        "--runtime-dir",
        str(tmp_path),
        "--thread",
        started["THREAD_ID"],
        "--approve",
        "--actor",
        "mallory",
        check=False,
    )
    assert result.returncode == 2
    assert "OUTCOME=refused" in result.stdout
    repository = SQLiteShopRepository(tmp_path / "shop.db", clock=lambda: "t")
    assert repository.load_state().revision == 1


def test_cli_refuses_a_swapped_provider_binding(tmp_path: Path) -> None:
    started = _cli_start(tmp_path)
    result = _cli(
        "decide",
        "--runtime-dir",
        str(tmp_path),
        "--thread",
        started["THREAD_ID"],
        "--approve",
        "--provider",
        "bedrock",
        check=False,
    )
    assert result.returncode == 2
    assert "binding does not match" in result.stdout
    repository = SQLiteShopRepository(tmp_path / "shop.db", clock=lambda: "t")
    assert repository.load_state().revision == 1


# --------------------------------------------------------------------------- integrity refusals


def _assert_refused(runtime: GraphRuntime, result: dict, reason: str) -> None:
    assert result["outcome"] == "refused", result
    assert reason in result["refusal_reason"]
    assert result["applied_revision"] is None
    assert runtime.repository.load_state().revision == 1
    events = _events(runtime)
    assert "plan_applied" not in events
    assert events[-1] == "apply_refused"


def test_forged_hash_in_thread_is_refused(runtime: GraphRuntime) -> None:
    thread_id, _ = _start(runtime)
    forged = "0" * 64
    runtime.graph.update_state(runtime.config(thread_id), {"proposal_hash": forged})

    result = runtime.resume(thread_id, approved=True, reviewed_hash=forged)

    _assert_refused(runtime, result, "does not match its claimed hash")


def test_altered_proposal_content_is_refused_even_with_original_hash(
    runtime: GraphRuntime,
) -> None:
    thread_id, _ = _start(runtime)
    proposal = dict(runtime.state(thread_id)["proposal"])
    proposal["procurement_actions"] = []
    runtime.graph.update_state(runtime.config(thread_id), {"proposal": proposal})

    result = runtime.resume(thread_id, approved=True)

    _assert_refused(runtime, result, "does not match its claimed hash")


def test_thread_proposal_differing_from_persisted_is_refused(runtime: GraphRuntime) -> None:
    thread_id, payload = _start(runtime)
    with sqlite3.connect(runtime.repository.path) as connection:
        row = connection.execute(
            "SELECT payload FROM production_proposals WHERE content_hash = ?",
            (payload["proposal_hash"],),
        ).fetchone()
        tampered = json.loads(row[0])
        tampered["target_order_id"] = "FORGED"
        connection.execute(
            "UPDATE production_proposals SET payload = ? WHERE content_hash = ?",
            (json.dumps(tampered), payload["proposal_hash"]),
        )

    result = runtime.resume(thread_id, approved=True)

    _assert_refused(runtime, result, "integrity")


def test_stale_revision_is_refused(runtime: GraphRuntime) -> None:
    thread_id, _ = _start(runtime)
    # A competing writer advanced the shop revision after the proposal was cut.
    with sqlite3.connect(runtime.repository.path) as connection:
        payload = json.loads(
            connection.execute("SELECT payload FROM shop_state WHERE singleton = 1").fetchone()[0]
        )
        payload["revision"] = 2
        connection.execute(
            "UPDATE shop_state SET payload = ? WHERE singleton = 1",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
        )

    result = runtime.resume(thread_id, approved=True)

    assert result["outcome"] == "refused"
    assert "State revision 2 does not match 1" in result["refusal_reason"]
    assert "plan_applied" not in _events(runtime)
    assert runtime.repository.load_state().revision == 2


def test_stale_digest_without_revision_change_is_refused(runtime: GraphRuntime) -> None:
    thread_id, _ = _start(runtime)
    with sqlite3.connect(runtime.repository.path) as connection:
        payload = json.loads(
            connection.execute("SELECT payload FROM shop_state WHERE singleton = 1").fetchone()[0]
        )
        payload["inventory"]["THREAD-RED-40"] = 99_999
        connection.execute(
            "UPDATE shop_state SET payload = ? WHERE singleton = 1",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
        )

    result = runtime.resume(thread_id, approved=True)

    _assert_refused(runtime, result, "Domain state changed")


def test_replayed_approval_after_apply_is_refused(runtime: GraphRuntime) -> None:
    thread_id, payload = _start(runtime)
    assert runtime.resume(thread_id, approved=True)["outcome"] == "applied"
    revision_after = runtime.repository.load_state().revision

    # Rewind the thread to the approval gate and replay the same approval.
    history = list(runtime.graph.get_state_history(runtime.config(thread_id)))
    at_gate = next(snapshot for snapshot in history if "approval_gate" in snapshot.next)
    result = runtime.graph.invoke(
        Command(
            resume={"approved": True, "actor": ACTOR, "reviewed_hash": payload["proposal_hash"]}
        ),
        at_gate.config,
    )

    assert result["outcome"] == "refused"
    assert "already applied" in result["refusal_reason"]
    assert runtime.repository.load_state().revision == revision_after
    assert _events(runtime).count("plan_applied") == 1


def test_double_approve_on_same_thread_is_refused(runtime: GraphRuntime) -> None:
    thread_id, _ = _start(runtime)
    runtime.resume(thread_id, approved=True)

    with pytest.raises(ApplyRefused, match="no pending"):
        runtime.resume(thread_id, approved=True)

    assert _events(runtime).count("plan_applied") == 1
    assert runtime.repository.load_state().revision == 2


def test_wrong_actor_is_refused(runtime: GraphRuntime) -> None:
    thread_id, _ = _start(runtime)
    result = runtime.resume(thread_id, approved=True, actor="mallory")
    _assert_refused(runtime, result, "actor does not match")
    assert _events(runtime)[-2] == "approval_granted"  # recorded, but never applied


def test_wrong_provider_binding_is_refused(tmp_path: Path) -> None:
    first = GraphRuntime(tmp_path, BINDING, planner=planner_for_scenario("rush-order"))
    thread_id, _ = _start(first)
    first.close()
    swapped = _fresh(tmp_path, {**BINDING, "provider": "bedrock-workflow"})
    try:
        result = swapped.resume(thread_id, approved=True)
        _assert_refused(swapped, result, "binding does not match")
    finally:
        swapped.close()


def test_wrong_model_binding_is_refused(tmp_path: Path) -> None:
    first = GraphRuntime(tmp_path, BINDING, planner=planner_for_scenario("rush-order"))
    thread_id, _ = _start(first)
    first.close()
    swapped = _fresh(tmp_path, {**BINDING, "model_id": "amazon.nova-lite-v1:0"})
    try:
        _assert_refused(swapped, swapped.resume(thread_id, approved=True), "binding")
    finally:
        swapped.close()


def test_approval_for_a_different_reviewed_hash_is_refused(runtime: GraphRuntime) -> None:
    thread_id, _ = _start(runtime)
    result = runtime.resume(thread_id, approved=True, reviewed_hash="f" * 64)
    _assert_refused(runtime, result, "exact proposal hash")


def test_persisted_decision_mismatch_is_refused(runtime: GraphRuntime) -> None:
    thread_id, payload = _start(runtime)
    # Simulate a thread that claims approval while the store never recorded one.
    runtime.graph.update_state(
        runtime.config(thread_id),
        {
            "decision": {
                "approved": True,
                "actor": ACTOR,
                "reviewed_hash": payload["proposal_hash"],
                "reason": "Approved through LangGraph interrupt",
            }
        },
        as_node="approval_gate",
    )
    result = runtime.graph.invoke(None, runtime.config(thread_id))
    _assert_refused(runtime, result, "not the decision recorded")


@pytest.mark.parametrize(
    "resume_value",
    [
        {"approved": True},
        {"approved": True, "actor": ACTOR},
        {"approved": "yes", "actor": ACTOR, "reviewed_hash": "x" * 64},
        42,
        "maybe",
    ],
)
def test_malformed_resume_value_defaults_to_denial(
    runtime: GraphRuntime, resume_value: object
) -> None:
    thread_id, payload = _start(runtime)

    result = runtime.graph.invoke(Command(resume=resume_value), runtime.config(thread_id))

    assert result["outcome"] == "rejected"
    assert result["decision"]["approved"] is False
    assert runtime.repository.load_state().revision == 1
    assert _events(runtime) == [*PENDING_EVENTS, "approval_rejected"]
    assert runtime.repository.latest_decision(payload["proposal_hash"]).approved is False


def test_rejection_reason_is_recorded_against_exact_hash(runtime: GraphRuntime) -> None:
    thread_id, payload = _start(runtime)
    runtime.resume(thread_id, approved=False)
    decision = runtime.repository.latest_decision(payload["proposal_hash"])
    assert decision is not None
    assert decision.approved is False
    assert decision.reviewed_hash == payload["proposal_hash"]
    assert decision.actor == ACTOR
    assert "LangGraph" in decision.reason


def test_replace_helper_keeps_models_immutable(runtime: GraphRuntime) -> None:
    thread_id, payload = _start(runtime)
    persisted = runtime.repository.load_proposal(payload["proposal_hash"])
    forged = replace(persisted, target_order_id="FORGED")
    with pytest.raises(ValueError, match="integrity"):
        runtime.repository.save_proposal(forged)
    assert runtime.pending_interrupt(thread_id) is not None
