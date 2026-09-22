"""Framework-neutral definitions of the eight shop tools.

Both agent frameworks in this repository (Strands in ``workflow.py``,
LangGraph in ``langgraph_workflow.py``) expose the same eight tools. The
business logic behind each tool lives on ``ShopService``; this module is
the single place that names the tools, orders them, declares their
arguments, and binds them to a service instance as plain callables. Each
framework adapts these plain callables to its own decorator or tool class
so neither can drift from the other.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from production_orchestrator.workflow import ShopService


@dataclass(frozen=True)
class ToolParameter:
    name: str
    annotation: type
    description: str


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: tuple[ToolParameter, ...] = ()
    requires_catalog: bool = False


INTAKE_TOOL = "intake_customer_request"
APPLY_TOOL = "apply_production_plan"

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name=INTAKE_TOOL,
        description="Validate an extracted customer request and add it to the order queue.",
        parameters=(
            ToolParameter("order_id", str, "The shop-assigned order identifier for this request."),
            ToolParameter(
                "product_code", str, "Exact catalog product code the customer is asking for."
            ),
            ToolParameter("quantity", int, "Number of units requested."),
            ToolParameter("requested_day", str, "Requested completion day (YYYY-MM-DD)."),
            ToolParameter("priority", int, "Urgency from 1 (lowest) to 100 (highest rush)."),
        ),
        requires_catalog=True,
    ),
    ToolSpec(
        name="list_active_orders",
        description=(
            "List active orders with exact priorities, due dates, requirements, and durations."
        ),
    ),
    ToolSpec(
        name="get_inventory",
        description="Return exact synthetic material availability for the current state revision.",
    ),
    ToolSpec(
        name="get_machine_capacity",
        description="Return exact machine capabilities, capacities, and scheduled commitments.",
    ),
    ToolSpec(
        name="analyze_shop_blockers",
        description="Deterministically identify inventory and machine-capacity blockers.",
        parameters=(ToolParameter("target_order_id", str, "Exact order identifier to analyze."),),
    ),
    ToolSpec(
        name="propose_schedule",
        description=(
            "Create a deterministic, versioned production proposal with an immutable hash."
        ),
        parameters=(ToolParameter("target_order_id", str, "Exact order identifier to schedule."),),
    ),
    ToolSpec(
        name="draft_communications",
        description="Return customer, operator, and supplier drafts bound to a proposal hash.",
        parameters=(
            ToolParameter("proposal_hash", str, "Immutable hash returned by propose_schedule."),
        ),
    ),
    ToolSpec(
        name=APPLY_TOOL,
        description="Apply the exact reviewed production plan after human approval.",
        parameters=(
            ToolParameter("proposal_hash", str, "Immutable hash returned by propose_schedule."),
        ),
    ),
)

TOOL_NAMES: tuple[str, ...] = tuple(spec.name for spec in TOOL_SPECS)
WORKFLOW_SEQUENCE: tuple[str, ...] = TOOL_NAMES
"""The order the governed loop calls the tools in, intake first, apply last."""


def tool_names_for(service: "ShopService") -> tuple[str, ...]:
    """Tools available to a service: intake only when a catalog is configured."""
    return tuple(
        spec.name for spec in TOOL_SPECS if not spec.requires_catalog or service.catalog is not None
    )


def bind_shop_tools(service: "ShopService") -> Mapping[str, Callable[..., dict[str, object]]]:
    """Bind every available tool to plain keyword-argument callables on ``service``."""

    def intake_customer_request(
        *, order_id: str, product_code: str, quantity: int, requested_day: str, priority: int
    ) -> dict[str, object]:
        return service.intake_customer_request(
            order_id=order_id,
            product_code=product_code,
            quantity=quantity,
            requested_day=requested_day,
            priority=priority,
        )

    def list_active_orders() -> dict[str, object]:
        return service.list_active_orders()

    def get_inventory() -> dict[str, object]:
        return service.get_inventory()

    def get_machine_capacity() -> dict[str, object]:
        return service.get_machine_capacity()

    def analyze_shop_blockers(*, target_order_id: str) -> dict[str, object]:
        return service.analyze_shop_blockers(target_order_id)

    def propose_schedule(*, target_order_id: str) -> dict[str, object]:
        return service.propose_schedule(target_order_id)

    def draft_communications(*, proposal_hash: str) -> dict[str, object]:
        return service.draft_communications(proposal_hash)

    def apply_production_plan(*, proposal_hash: str) -> dict[str, object]:
        return service.apply_plan(proposal_hash)

    implementations: dict[str, Callable[..., dict[str, object]]] = {
        INTAKE_TOOL: intake_customer_request,
        "list_active_orders": list_active_orders,
        "get_inventory": get_inventory,
        "get_machine_capacity": get_machine_capacity,
        "analyze_shop_blockers": analyze_shop_blockers,
        "propose_schedule": propose_schedule,
        "draft_communications": draft_communications,
        APPLY_TOOL: apply_production_plan,
    }
    return {name: implementations[name] for name in tool_names_for(service)}


def spec_for(name: str) -> ToolSpec:
    for spec in TOOL_SPECS:
        if spec.name == name:
            return spec
    raise KeyError(f"Unknown tool: {name}")


def invoke_tool(
    bound: Mapping[str, Callable[..., dict[str, object]]], name: str, arguments: Mapping[str, Any]
) -> dict[str, object]:
    """Invoke a bound tool with validated argument names."""
    spec = spec_for(name)
    expected = {parameter.name for parameter in spec.parameters}
    if set(arguments) != expected:
        raise TypeError(f"{name} expects arguments {sorted(expected)}, got {sorted(arguments)}")
    return bound[name](**arguments)
