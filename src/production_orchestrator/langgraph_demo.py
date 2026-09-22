"""Two-process demo of the LangGraph governed loop.

``start`` runs the graph to the approval interrupt and prints the proposal
and its hash; ``decide`` resumes the persisted thread in a fresh process.
This mirrors ``restart_spike.py`` for the Strands path: the thread is
reloaded from the SqliteSaver checkpoint, the pending interrupt is
re-observed, and the decision is submitted through ``Command(resume=...)``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from production_orchestrator.fixtures import SCENARIOS
from production_orchestrator.langgraph_workflow import (
    LANGGRAPH_MODEL_ID,
    LANGGRAPH_PROVIDER,
    ApplyRefused,
    GraphRuntime,
    RuntimeBinding,
    planner_for_scenario,
)

DEFAULT_ACTOR = "langgraph-demo-operator"


def _binding(args: argparse.Namespace) -> RuntimeBinding:
    return {"actor": args.actor, "provider": args.provider, "model_id": args.model}


def start(args: argparse.Namespace) -> dict[str, object]:
    runtime = GraphRuntime(
        args.runtime_dir, _binding(args), planner=planner_for_scenario(args.scenario)
    )
    try:
        started = runtime.start(args.scenario, thread_id=args.thread)
        thread_id = started["thread_id"]
        payload = started["interrupt"]
        state = runtime.state(thread_id)
        report = {
            "thread_id": thread_id,
            "scenario": args.scenario,
            "proposal_hash": payload["proposal_hash"],
            "proposal": json.loads(payload["proposal"]),
            "summary": payload["summary"],
            "tool_calls": [call["name"] for call in state["tool_calls"]],
            "shop_revision": runtime.repository.load_state().revision,
            "start_process_id": os.getpid(),
            "checkpoint_db": str(runtime.runtime_dir / "langgraph_checkpoints.db"),
        }
    finally:
        runtime.close()
    print(f"THREAD_ID={thread_id}")
    print(f"PROPOSAL_HASH={report['proposal_hash']}")
    print("TOOL_CALLS=" + ",".join(report["tool_calls"]))
    print("PROPOSAL=" + payload["proposal"])
    return report


def decide(args: argparse.Namespace) -> dict[str, object]:
    runtime = GraphRuntime(args.runtime_dir, _binding(args))
    try:
        pending = runtime.pending_interrupt(args.thread)
        if pending is None:
            print("RESULT=refused", file=sys.stderr)
            print("REASON=Thread has no pending approval interrupt", file=sys.stderr)
            raise SystemExit(2)
        approved = bool(args.approve)
        try:
            result = runtime.resume(args.thread, approved=approved, actor=args.actor)
        except ApplyRefused as error:
            print("RESULT=refused", file=sys.stderr)
            print(f"REASON={error}", file=sys.stderr)
            raise SystemExit(2) from error
        state = runtime.repository.load_state()
        audit = [event.event_type for event in runtime.repository.audit_events()]
        recorded = result.get("decision") or {}
        denied_at_gate = approved and recorded.get("approved") is False
        report = {
            "thread_id": args.thread,
            "decision": "approve" if approved else "reject",
            "outcome": result.get("outcome"),
            "refusal_reason": (
                recorded.get("reason") if denied_at_gate else result.get("refusal_reason")
            ),
            "proposal_hash": pending["proposal_hash"],
            "final_state_revision": state.revision,
            "plan_applied_count": audit.count("plan_applied"),
            "audit_event_types": audit,
            "resume_process_id": os.getpid(),
        }
    finally:
        runtime.close()
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"DECISION={report['decision']}")
    print(f"OUTCOME={report['outcome']}")
    print(f"FINAL_STATE_REVISION={state.revision}")
    print(f"PLAN_APPLIED_COUNT={report['plan_applied_count']}")
    if report["outcome"] == "refused" or denied_at_gate:
        print(f"REASON={report['refusal_reason']}")
        raise SystemExit(2)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LangGraph governed-loop demo")
    subparsers = parser.add_subparsers(dest="phase", required=True)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--runtime-dir", type=Path, required=True)
        sub.add_argument("--actor", default=DEFAULT_ACTOR)
        sub.add_argument("--provider", default=LANGGRAPH_PROVIDER)
        sub.add_argument("--model", default=LANGGRAPH_MODEL_ID)

    start_parser = subparsers.add_parser("start", help="run to the approval interrupt")
    common(start_parser)
    start_parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="rush-order")
    start_parser.add_argument("--thread", help="explicit thread id (default: random)")
    start_parser.set_defaults(handler=start)

    decide_parser = subparsers.add_parser("decide", help="resume a pending thread")
    common(decide_parser)
    decide_parser.add_argument("--thread", required=True)
    decide_parser.add_argument("--report", type=Path)
    group = decide_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--approve", action="store_true")
    group.add_argument("--reject", action="store_true")
    decide_parser.set_defaults(handler=decide)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main()
