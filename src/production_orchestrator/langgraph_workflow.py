"""LangGraph implementation of the governed production-planning loop.

This is the same loop ``workflow.py`` runs under Strands, expressed as a
``StateGraph``: the same eight tools bound through ``tool_specs``, the same
deterministic planner, the same immutable hash-addressed proposal, and the
same fail-closed application step. The differences are where the human
pause lives (``langgraph.types.interrupt`` inside the ``approval_gate`` node
instead of a ``BeforeToolCallEvent`` hook) and where the thread survives a
process death (``SqliteSaver`` instead of ``FileSessionManager``).

Nothing in this module calculates a shop fact. Every number comes from a
tool call into ``ShopService``, and ``approval.apply_production_plan`` is the
only path that writes to the shop.
"""

from __future__ import annotations

import json
import operator
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field, create_model

from production_orchestrator.approval import (
    ApprovalRejected,
    ApprovalRequired,
    ProposalIntegrityError,
    StaleProposal,
    apply_production_plan,
)
from production_orchestrator.fixtures import SCENARIOS
from production_orchestrator.intake import RequestExtraction
from production_orchestrator.persistence import SQLiteShopRepository, proposal_from_payload
from production_orchestrator.planning import calculate_production_plan_hash
from production_orchestrator.spike import utc_now
from production_orchestrator.tool_specs import (
    APPLY_TOOL,
    INTAKE_TOOL,
    TOOL_SPECS,
    ToolSpec,
    bind_shop_tools,
    spec_for,
)
from production_orchestrator.workflow import ShopService

LANGGRAPH_PROVIDER = "deterministic-langgraph"
LANGGRAPH_MODEL_ID = "deterministic-workflow-model"
INTERRUPT_NAME = "production-orchestrator-apply-plan"
CHECKPOINT_DB = "langgraph_checkpoints.db"
SHOP_DB = "shop.db"

ANALYZE_TOOLS: tuple[str, ...] = (
    "list_active_orders",
    "get_inventory",
    "get_machine_capacity",
    "analyze_shop_blockers",
)
PLAN_TOOLS: tuple[str, ...] = ("propose_schedule", "draft_communications")


# --------------------------------------------------------------------------- state


class ToolCall(TypedDict):
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


class RuntimeBinding(TypedDict):
    """Who the thread acts as and which model provider it is entitled to.

    Persisted in the thread at ``start`` and compared, field by field, with
    the binding the resuming process was launched with. A mismatch refuses
    the application exactly like a swapped AWS profile does on the Strands
    path.
    """

    actor: str
    provider: str
    model_id: str


class Decision(TypedDict):
    approved: bool
    actor: str
    reviewed_hash: str
    reason: str


class OrchestratorState(TypedDict, total=False):
    thread_id: str
    scenario: str
    target_order_id: str
    request: dict[str, Any]
    binding: RuntimeBinding
    tool_calls: Annotated[list[ToolCall], operator.add]
    proposal: dict[str, Any] | None
    proposal_hash: str | None
    proposal_revision: int | None
    proposal_digest: str | None
    decision: Decision | None
    outcome: Literal["applied", "rejected", "refused"] | None
    refusal_reason: str | None
    applied_revision: int | None


# --------------------------------------------------------------------------- model adapter


@dataclass(frozen=True)
class PlannedCall:
    name: str
    arguments: dict[str, Any]


class ToolPlanner:
    """The "model step": decides which tool to call next given the history.

    The deterministic planner below mirrors ``restart_spike.DeterministicWorkflowModel``
    so the LangGraph path runs offline. A live model would implement the
    same single method; the graph never lets it invent shop facts because
    every result comes from a bound tool.
    """

    def next_call(self, phase: str, state: OrchestratorState) -> PlannedCall | None:
        raise NotImplementedError


class DeterministicToolPlanner(ToolPlanner):
    def __init__(self, extraction: RequestExtraction) -> None:
        self.extraction = extraction

    @staticmethod
    def _proposal_hash_from(state: OrchestratorState) -> str:
        for call in state.get("tool_calls", []):
            if call["name"] == "propose_schedule":
                candidate = call["result"].get("content_hash")
                if isinstance(candidate, str) and len(candidate) == 64:
                    return candidate
        raise RuntimeError("Proposal hash is not available from the propose_schedule result")

    def next_call(self, phase: str, state: OrchestratorState) -> PlannedCall | None:
        seen = [call["name"] for call in state.get("tool_calls", [])]
        sequence = {
            "intake": (INTAKE_TOOL,),
            "analyze": ANALYZE_TOOLS,
            "plan": PLAN_TOOLS,
        }[phase]
        name = next((tool for tool in sequence if tool not in seen), None)
        if name is None:
            return None
        if name == INTAKE_TOOL:
            return PlannedCall(name, asdict(self.extraction))
        if name in {"analyze_shop_blockers", "propose_schedule"}:
            return PlannedCall(name, {"target_order_id": state["target_order_id"]})
        if name == "draft_communications":
            return PlannedCall(name, {"proposal_hash": self._proposal_hash_from(state)})
        return PlannedCall(name, {})


def planner_for_scenario(scenario: str) -> DeterministicToolPlanner:
    spec = SCENARIOS[scenario]
    if spec.expected_extraction is None:
        raise ValueError(f"Scenario {scenario} has no deterministic extraction")
    return DeterministicToolPlanner(spec.expected_extraction)


# --------------------------------------------------------------------------- tools


def _args_schema(spec: ToolSpec) -> type[BaseModel]:
    fields: dict[str, Any] = {
        parameter.name: (parameter.annotation, Field(description=parameter.description))
        for parameter in spec.parameters
    }
    return create_model(f"{spec.name}_arguments", **fields)


def build_langgraph_tools(service: ShopService) -> dict[str, StructuredTool]:
    """Expose the shared tool bindings as LangChain ``StructuredTool`` objects.

    The name, description, argument names, and order are read from
    ``tool_specs`` — the same source the Strands ``@tool`` surface uses — so
    a reader can verify both frameworks expose an identical tool set.
    """
    bound = bind_shop_tools(service)
    tools: dict[str, StructuredTool] = {}
    for spec in TOOL_SPECS:
        if spec.name not in bound:
            continue
        tools[spec.name] = StructuredTool.from_function(
            func=bound[spec.name],
            name=spec.name,
            description=spec.description,
            args_schema=_args_schema(spec),
        )
    return tools


# --------------------------------------------------------------------------- graph


class ApplyRefused(RuntimeError):
    """An integrity check failed before mutation; the plan was not applied."""


@dataclass
class GraphRuntime:
    """Everything one process needs to start or resume a governed thread."""

    runtime_dir: Path
    binding: RuntimeBinding
    planner: ToolPlanner | None = None
    clock: Callable[[], str] = utc_now

    def __post_init__(self) -> None:
        self.runtime_dir = Path(self.runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.repository = SQLiteShopRepository(self.runtime_dir / SHOP_DB, clock=self.clock)
        self._connection = sqlite3.connect(
            self.runtime_dir / CHECKPOINT_DB, check_same_thread=False
        )
        self.checkpointer = SqliteSaver(self._connection)
        self._service: ShopService | None = None
        self.graph = build_graph(self)

    def close(self) -> None:
        self._connection.close()

    def service_for(self, scenario: str) -> ShopService:
        if self._service is None:
            self._service = ShopService(self.repository, catalog=SCENARIOS[scenario].catalog)
        return self._service

    @staticmethod
    def config(thread_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": thread_id}}

    # ---- public operations -------------------------------------------------

    def start(self, scenario: str, *, thread_id: str | None = None) -> dict[str, Any]:
        """Run to the approval interrupt and return the pending payload."""
        if scenario not in SCENARIOS:
            raise ValueError("Invalid scenario name")
        if self.planner is None:
            raise RuntimeError("Starting a thread requires a tool planner")
        spec = SCENARIOS[scenario]
        self.repository.initialize(spec.build_initial())
        thread_id = thread_id or uuid4().hex
        initial: OrchestratorState = {
            "thread_id": thread_id,
            "scenario": scenario,
            "target_order_id": spec.target_order_id,
            "request": {
                "customer_email": spec.customer_email,
                "catalog_codes": sorted(spec.catalog),
            },
            "binding": dict(self.binding),  # type: ignore[typeddict-item]
            "tool_calls": [],
            "proposal": None,
            "proposal_hash": None,
            "proposal_revision": None,
            "proposal_digest": None,
            "decision": None,
            "outcome": None,
            "refusal_reason": None,
            "applied_revision": None,
        }
        result = self.graph.invoke(initial, self.config(thread_id))
        interrupts = result.get("__interrupt__", ())
        if len(interrupts) != 1:
            raise RuntimeError("Expected exactly one LangGraph interrupt")
        payload = interrupts[0].value
        if payload.get("proposal_hash") != result.get("proposal_hash"):
            raise RuntimeError("Interrupt did not bind the thread's proposal hash")
        return {"thread_id": thread_id, "interrupt": payload}

    def pending_interrupt(self, thread_id: str) -> dict[str, Any] | None:
        """The interrupt a fresh process sees for this thread, or ``None``."""
        snapshot = self.graph.get_state(self.config(thread_id))
        if not snapshot.values or "approval_gate" not in tuple(snapshot.next):
            return None
        for task in snapshot.tasks:
            for pending in getattr(task, "interrupts", ()):
                return dict(pending.value)
        return None

    def resume(
        self,
        thread_id: str,
        *,
        approved: bool,
        reviewed_hash: str | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Resume a pending thread with a decision. Refuses when nothing is pending."""
        pending = self.pending_interrupt(thread_id)
        if pending is None:
            raise ApplyRefused("Thread has no pending approval interrupt")
        resume_value = {
            "approved": approved,
            "actor": self.binding["actor"] if actor is None else actor,
            "reviewed_hash": pending["proposal_hash"] if reviewed_hash is None else reviewed_hash,
        }
        return self.graph.invoke(Command(resume=resume_value), self.config(thread_id))

    def state(self, thread_id: str) -> dict[str, Any]:
        return dict(self.graph.get_state(self.config(thread_id)).values)


def build_graph(runtime: GraphRuntime):
    def _invoke(state: OrchestratorState, call: PlannedCall) -> ToolCall:
        tools = build_langgraph_tools(runtime.service_for(state["scenario"]))
        spec_for(call.name)  # unknown tool names fail before any call
        result = tools[call.name].invoke(dict(call.arguments))
        return {"name": call.name, "arguments": dict(call.arguments), "result": result}

    def _run_phase(state: OrchestratorState, phase: str) -> list[ToolCall]:
        if runtime.planner is None:
            raise RuntimeError("This process has no tool planner; it can only resume threads")
        calls: list[ToolCall] = []
        cursor: OrchestratorState = {**state, "tool_calls": list(state.get("tool_calls", []))}
        while (planned := runtime.planner.next_call(phase, cursor)) is not None:
            if planned.name == APPLY_TOOL:
                raise RuntimeError("The planner may not call apply_production_plan directly")
            executed = _invoke(cursor, planned)
            calls.append(executed)
            cursor = {**cursor, "tool_calls": [*cursor["tool_calls"], executed]}
        return calls

    def intake(state: OrchestratorState) -> dict[str, Any]:
        return {"tool_calls": _run_phase(state, "intake")}

    def analyze(state: OrchestratorState) -> dict[str, Any]:
        return {"tool_calls": _run_phase(state, "analyze")}

    def plan(state: OrchestratorState) -> dict[str, Any]:
        calls = _run_phase(state, "plan")
        proposal = next(call["result"] for call in calls if call["name"] == "propose_schedule")
        content_hash = proposal["content_hash"]
        if calculate_production_plan_hash(proposal_from_payload(proposal)) != content_hash:
            raise ProposalIntegrityError("Planner returned a proposal that does not match its hash")
        return {
            "tool_calls": calls,
            "proposal": proposal,
            "proposal_hash": content_hash,
            "proposal_revision": proposal["base_revision"],
            "proposal_digest": runtime.repository.domain_digest(),
        }

    def approval_gate(state: OrchestratorState) -> dict[str, Any]:
        proposal_hash = state["proposal_hash"]
        service = runtime.service_for(state["scenario"])
        payload = {
            "name": INTERRUPT_NAME,
            "proposal_hash": proposal_hash,
            "proposal": canonical_proposal_json(state["proposal"]),
            "summary": service.proposal_summary(proposal_hash),
        }
        response = interrupt(payload)
        decision = _normalize_decision(response, proposal_hash)
        service.repository.record_decision(
            proposal_hash=proposal_hash,
            reviewed_hash=decision["reviewed_hash"],
            approved=decision["approved"],
            actor=decision["actor"],
            reason=decision["reason"],
        )
        return {"decision": decision}

    def route_decision(state: OrchestratorState) -> str:
        decision = state.get("decision")
        return "apply" if decision is not None and decision["approved"] else "rejected"

    def apply(state: OrchestratorState) -> dict[str, Any]:
        try:
            applied_revision = _verify_and_apply(runtime, state)
        except (
            ApplyRefused,
            ApprovalRejected,
            ApprovalRequired,
            ProposalIntegrityError,
            StaleProposal,
            ValueError,
        ) as error:
            runtime.repository.record_audit(
                event_type="apply_refused",
                proposal_hash=state.get("proposal_hash"),
                details={"reason": str(error), "thread_id": state["thread_id"]},
            )
            return {"outcome": "refused", "refusal_reason": str(error)}
        return {"outcome": "applied", "applied_revision": applied_revision}

    def route_apply(state: OrchestratorState) -> str:
        return "done" if state.get("outcome") == "applied" else "rejected"

    def rejected(state: OrchestratorState) -> dict[str, Any]:
        if state.get("outcome") == "refused":
            return {}
        return {"outcome": "rejected"}

    def done(state: OrchestratorState) -> dict[str, Any]:
        return {}

    graph = StateGraph(OrchestratorState)
    graph.add_node("intake", intake)
    graph.add_node("analyze", analyze)
    graph.add_node("plan", plan)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("apply", apply)
    graph.add_node("rejected", rejected)
    graph.add_node("done", done)
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "analyze")
    graph.add_edge("analyze", "plan")
    graph.add_edge("plan", "approval_gate")
    graph.add_conditional_edges(
        "approval_gate", route_decision, {"apply": "apply", "rejected": "rejected"}
    )
    graph.add_conditional_edges("apply", route_apply, {"done": "done", "rejected": "rejected"})
    graph.add_edge("rejected", END)
    graph.add_edge("done", END)
    return graph.compile(checkpointer=runtime.checkpointer)


# --------------------------------------------------------------------------- integrity


def canonical_proposal_json(proposal: Mapping[str, Any] | None) -> str:
    return json.dumps(proposal, sort_keys=True, separators=(",", ":"))


def _normalize_decision(response: Any, proposal_hash: str) -> Decision:
    if isinstance(response, str):
        approved = response.strip().lower() in {"y", "yes", "approve", "approved"}
        return {
            "approved": approved,
            "actor": "unknown",
            "reviewed_hash": proposal_hash,
            "reason": _reason(approved),
        }
    if not isinstance(response, Mapping):
        raise TypeError("Resume value must be a decision mapping")
    approved = bool(response.get("approved", False))
    actor = response.get("actor")
    reviewed_hash = response.get("reviewed_hash")
    if not isinstance(actor, str) or not actor:
        raise TypeError("Resume value must name the deciding actor")
    if not isinstance(reviewed_hash, str) or not reviewed_hash:
        raise TypeError("Resume value must name the reviewed proposal hash")
    return {
        "approved": approved,
        "actor": actor,
        "reviewed_hash": reviewed_hash,
        "reason": _reason(approved),
    }


def _reason(approved: bool) -> str:
    return (
        "Approved through LangGraph interrupt"
        if approved
        else "Rejected through LangGraph interrupt"
    )


def _verify_and_apply(runtime: GraphRuntime, state: OrchestratorState) -> int:
    """Re-run every integrity check the Strands path enforces, then apply once.

    Order matters: every refusal happens before ``apply_production_plan`` is
    reached, and that function performs the same hash / decision / staleness
    checks again on the persisted proposal — the shop is never mutated by a
    proposal that fails any of them.
    """
    repository = runtime.repository
    decision = state.get("decision")
    proposal_payload = state.get("proposal")
    claimed_hash = state.get("proposal_hash")
    if decision is None or not decision["approved"]:
        raise ApprovalRequired("No approval recorded on this thread")
    if state.get("outcome") == "applied":
        raise ApplyRefused("Thread already applied its proposal")
    if not isinstance(proposal_payload, Mapping) or not isinstance(claimed_hash, str):
        raise ProposalIntegrityError("Thread carries no proposal to apply")

    # 1. Hash: the proposal content in the thread must still hash to the claimed hash,
    #    and the persisted proposal under that hash must be byte-identical to it.
    proposal = proposal_from_payload(dict(proposal_payload))
    if calculate_production_plan_hash(proposal) != claimed_hash or proposal.content_hash != (
        claimed_hash
    ):
        raise ProposalIntegrityError("Thread proposal content does not match its claimed hash")
    persisted = repository.load_proposal(claimed_hash)
    if persisted is None or persisted != proposal:
        raise ProposalIntegrityError("Thread proposal does not match the persisted proposal")

    # 2. Identity and provider binding: the deciding actor and the resuming process must
    #    both match what the thread was started with.
    binding = state.get("binding")
    if binding is None or dict(binding) != dict(runtime.binding):
        raise ApplyRefused("Thread binding does not match the resuming process configuration")
    if decision["actor"] != binding["actor"]:
        raise ApplyRefused("Decision actor does not match the thread's bound actor")

    # 3. Approval binds to the exact reviewed hash.
    if decision["reviewed_hash"] != claimed_hash:
        raise ProposalIntegrityError("Approval does not bind to the exact proposal hash")

    # 4. Not replayed: the persisted decision must be the one this gate just recorded, and
    #    the plan must not have been applied already.
    latest = repository.latest_decision(claimed_hash)
    if (
        latest is None
        or latest.reviewed_hash != decision["reviewed_hash"]
        or latest.actor != decision["actor"]
        or latest.reason != decision["reason"]
        or not latest.approved
    ):
        raise ApplyRefused("Persisted decision is not the decision recorded by this thread")
    if any(
        event.event_type == "plan_applied" and event.proposal_hash == claimed_hash
        for event in repository.audit_events()
    ):
        raise ApplyRefused("Proposal was already applied")

    # 5. Shop state unchanged since the proposal was cut.
    current = repository.load_state()
    if current.revision != state.get("proposal_revision") or current.revision != (
        proposal.base_revision
    ):
        raise StaleProposal(
            f"State revision {current.revision} does not match {proposal.base_revision}"
        )
    if repository.domain_digest() != state.get("proposal_digest"):
        raise StaleProposal("Domain state changed after the proposal was cut")

    return apply_production_plan(repository, persisted).applied_revision
