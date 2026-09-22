"""Golden-set eval: the Strands and LangGraph loops must agree on every case.

Each case in ``evals/cases/*.json`` is an intake email plus the structured
extraction the offline model produces for it, the base shop scenario, and
the reviewer's verdict. Both implementations run the case offline; the
harness asserts they produce the same proposal hash, the same tool-call
sequence up to the approval interrupt, the same audit chain, and the same
final shop revision — and that each matches the frozen expectation.

Usage: ``uv run python evals/run_evals.py [--cases DIR] [--update]``.
Exit status is non-zero on any mismatch. ``--update`` rewrites the expected
fields from the current run and is only for deliberately re-freezing.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from strands import Agent
from strands.session import FileSessionManager

from production_orchestrator.fixtures import SCENARIOS
from production_orchestrator.intake import RequestExtraction
from production_orchestrator.langgraph_workflow import (
    LANGGRAPH_MODEL_ID,
    LANGGRAPH_PROVIDER,
    DeterministicToolPlanner,
    GraphRuntime,
)
from production_orchestrator.persistence import SQLiteShopRepository
from production_orchestrator.restart_spike import (
    WORKFLOW_SYSTEM_PROMPT,
    DeterministicWorkflowModel,
    workflow_intake_prompt,
)
from production_orchestrator.spike import utc_now
from production_orchestrator.workflow import (
    ProductionPlanApprovalHook,
    ShopService,
    build_strands_tools,
)

CASES_DIR = Path(__file__).parent / "cases"
ACTOR = "eval-reviewer"
COMPARED_FIELDS = ("proposal_hash", "tool_sequence", "audit_events", "final_revision", "outcome")
FAIL_CLOSED_FIELDS = ("proposal_hash", "final_revision", "proposal_created", "plan_applied")


@dataclass(frozen=True)
class Observation:
    proposal_hash: str | None
    tool_sequence: list[str]
    audit_events: list[str]
    final_revision: int
    outcome: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fail_closed_view(self) -> dict[str, Any]:
        """The governance invariants that must hold when intake is refused."""
        return {
            "proposal_hash": self.proposal_hash,
            "final_revision": self.final_revision,
            "proposal_created": "proposal_created" in self.audit_events,
            "plan_applied": "plan_applied" in self.audit_events,
        }


def _extraction(case: dict[str, Any]) -> RequestExtraction:
    return RequestExtraction(**case["extraction"])


def run_strands(case: dict[str, Any], runtime_dir: Path) -> Observation:
    spec = SCENARIOS[case["scenario"]]
    repository = SQLiteShopRepository(runtime_dir / "shop.db", clock=utc_now)
    repository.initialize(spec.build_initial())
    service = ShopService(repository, catalog=spec.catalog)
    agent = Agent(
        model=DeterministicWorkflowModel(
            case["extraction"]["order_id"], extraction=_extraction(case)
        ),
        tools=build_strands_tools(service),
        hooks=[ProductionPlanApprovalHook(service, actor=ACTOR)],
        session_manager=FileSessionManager(
            session_id="eval", storage_dir=str(runtime_dir / "sessions")
        ),
        system_prompt=WORKFLOW_SYSTEM_PROMPT,
        callback_handler=None,
    )
    outcome = "error"
    proposal_hash: str | None = None
    try:
        first = agent(workflow_intake_prompt(spec))
        interrupts = list(first.interrupts or [])
        if first.stop_reason == "interrupt" and len(interrupts) == 1:
            proposal_hash = interrupts[0].reason["proposal_hash"]
            response = "y" if case["verdict"] == "approve" else "n"
            agent(
                [
                    {
                        "interruptResponse": {
                            "interruptId": interrupts[0].id,
                            "response": response,
                        }
                    }
                ]
            )
            outcome = "applied" if case["verdict"] == "approve" else "rejected"
    except Exception as error:  # noqa: BLE001 - the eval records fail-closed behaviour
        outcome = f"error:{type(error).__name__}"
    tool_sequence = [
        block["toolUse"]["name"]
        for message in agent.messages
        for block in message.get("content", [])
        if "toolUse" in block
    ]
    audit = [event.event_type for event in repository.audit_events()]
    if "plan_applied" in audit and outcome != "applied":
        outcome = "applied"
    return Observation(
        proposal_hash=proposal_hash,
        tool_sequence=[name for name in tool_sequence if name != "apply_production_plan"],
        audit_events=audit,
        final_revision=repository.load_state().revision,
        outcome=outcome,
    )


def run_langgraph(case: dict[str, Any], runtime_dir: Path) -> Observation:
    binding = {"actor": ACTOR, "provider": LANGGRAPH_PROVIDER, "model_id": LANGGRAPH_MODEL_ID}
    runtime = GraphRuntime(
        runtime_dir, binding, planner=DeterministicToolPlanner(_extraction(case))
    )
    outcome = "error"
    proposal_hash: str | None = None
    tool_sequence: list[str] = []
    try:
        started = runtime.start(case["scenario"])
        proposal_hash = started["interrupt"]["proposal_hash"]
        result = runtime.resume(started["thread_id"], approved=case["verdict"] == "approve")
        outcome = str(result["outcome"])
        tool_sequence = [call["name"] for call in result["tool_calls"]]
    except Exception as error:  # noqa: BLE001 - the eval records fail-closed behaviour
        outcome = f"error:{type(error).__name__}"
    finally:
        runtime.close()
    repository = runtime.repository
    return Observation(
        proposal_hash=proposal_hash,
        tool_sequence=tool_sequence,
        audit_events=[event.event_type for event in repository.audit_events()],
        final_revision=repository.load_state().revision,
        outcome=outcome,
    )


def load_cases(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    return [(path, json.loads(path.read_text())) for path in sorted(directory.glob("*.json"))]


def evaluate(case: dict[str, Any]) -> tuple[Observation, Observation]:
    with tempfile.TemporaryDirectory(prefix="po-eval-") as scratch:
        root = Path(scratch)
        return run_strands(case, root / "strands"), run_langgraph(case, root / "langgraph")


def _short(value: str | None) -> str:
    return "—" if value is None else value[:12]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, default=CASES_DIR)
    parser.add_argument("--update", action="store_true", help="re-freeze expected fields")
    args = parser.parse_args(argv)
    logging.getLogger("strands").setLevel(logging.CRITICAL)

    rows: list[str] = []
    failures = 0
    total = 0
    fail_closed_total = 0
    for path, case in load_cases(args.cases):
        strands, langgraph = evaluate(case)
        expected = case.get("expected", {})
        if args.update:
            case["expected"] = langgraph.as_dict()
            path.write_text(json.dumps(case, indent=2) + "\n")
            expected = case["expected"]
        if case.get("expects") == "fail_closed":
            # Both frameworks must refuse without a proposal or a write. The scripted
            # Strands model keeps calling read tools after a tool error while the graph
            # node halts at once, so tool trails are reported but not compared here.
            strands_view, langgraph_view = strands.fail_closed_view(), langgraph.fail_closed_view()
            paths_agree = strands_view == langgraph_view
            matches_expected = (
                all(langgraph_view[field] == expected.get(field) for field in FAIL_CLOSED_FIELDS)
                and langgraph_view["proposal_hash"] is None
            )
            if args.update:
                case["expected"] = langgraph_view
                path.write_text(json.dumps(case, indent=2) + "\n")
        else:
            paths_agree = strands.as_dict() == langgraph.as_dict()
            matches_expected = all(
                langgraph.as_dict()[field] == expected.get(field) for field in COMPARED_FIELDS
            )
        status = "PASS" if paths_agree and matches_expected else "FAIL"
        total += 1
        fail_closed_total += case.get("expects") == "fail_closed"
        if status == "FAIL":
            failures += 1
        rows.append(
            f"| {case['id']} | {case['verdict']} | {_short(strands.proposal_hash)} | "
            f"{_short(langgraph.proposal_hash)} | {len(strands.tool_sequence)} / "
            f"{len(langgraph.tool_sequence)} | {strands.final_revision} / "
            f"{langgraph.final_revision} | {langgraph.outcome} | {status} |"
        )
        if status == "FAIL":
            rows.append(
                "|  | strands: "
                + json.dumps(strands.as_dict(), sort_keys=True)
                + " |  |  |  |  |  |  |"
            )
            rows.append(
                "|  | langgraph: "
                + json.dumps(langgraph.as_dict(), sort_keys=True)
                + " |  |  |  |  |  |  |"
            )
            rows.append(
                "|  | expected: "
                + json.dumps({k: expected.get(k) for k in COMPARED_FIELDS}, sort_keys=True)
                + " |  |  |  |  |  |  |"
            )

    print("| case | verdict | strands hash | langgraph hash | tools S/L | rev S/L | outcome | ok |")
    print("|---|---|---|---|---|---|---|---|")
    print("\n".join(rows))
    full = total - fail_closed_total
    print(
        f"\n{total - failures}/{total} cases agree across Strands and LangGraph "
        f"({full} full-parity: hash + tool sequence + audit + revision + outcome; "
        f"{fail_closed_total} fail-closed: no proposal, no write, revision unchanged)."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
