from pathlib import Path

import pytest

from production_orchestrator.fixtures import SCENARIOS
from production_orchestrator.persistence import SQLiteShopRepository
from production_orchestrator.tool_specs import (
    APPLY_TOOL,
    INTAKE_TOOL,
    TOOL_NAMES,
    TOOL_SPECS,
    WORKFLOW_SEQUENCE,
    bind_shop_tools,
    invoke_tool,
    spec_for,
    tool_names_for,
)
from production_orchestrator.workflow import ShopService, build_strands_tools


def _service(tmp_path: Path, *, with_catalog: bool) -> tuple[SQLiteShopRepository, ShopService]:
    spec = SCENARIOS["rush-order"]
    repository = SQLiteShopRepository(tmp_path / "shop.db", clock=lambda: "2026-08-11T18:00:00Z")
    repository.initialize(spec.build())
    return repository, ShopService(repository, catalog=spec.catalog if with_catalog else None)


def test_spec_names_eight_tools_intake_first_apply_last() -> None:
    assert len(TOOL_SPECS) == 8
    assert TOOL_NAMES[0] == INTAKE_TOOL
    assert TOOL_NAMES[-1] == APPLY_TOOL
    assert WORKFLOW_SEQUENCE == TOOL_NAMES
    assert len(set(TOOL_NAMES)) == 8


def test_intake_is_the_only_catalog_gated_tool() -> None:
    gated = [spec.name for spec in TOOL_SPECS if spec.requires_catalog]
    assert gated == [INTAKE_TOOL]


def test_strands_surface_matches_shared_spec_with_and_without_catalog(tmp_path: Path) -> None:
    _, with_catalog = _service(tmp_path / "a", with_catalog=True)
    _, without_catalog = _service(tmp_path / "b", with_catalog=False)

    assert [t.tool_name for t in build_strands_tools(with_catalog)] == list(TOOL_NAMES)
    assert [t.tool_name for t in build_strands_tools(without_catalog)] == list(TOOL_NAMES[1:])
    assert tool_names_for(with_catalog) == TOOL_NAMES
    assert tool_names_for(without_catalog) == TOOL_NAMES[1:]


def test_strands_tool_schemas_declare_the_shared_parameters(tmp_path: Path) -> None:
    _, service = _service(tmp_path, with_catalog=True)
    for strands_tool in build_strands_tools(service):
        spec = spec_for(strands_tool.tool_name)
        schema = strands_tool.tool_spec["inputSchema"]["json"]
        assert set(schema.get("properties", {})) == {p.name for p in spec.parameters}
        assert strands_tool.tool_spec["description"].splitlines()[0] == spec.description


def test_bound_tools_share_service_side_effects(tmp_path: Path) -> None:
    repository, service = _service(tmp_path, with_catalog=False)
    bound = bind_shop_tools(service)

    proposal = invoke_tool(bound, "propose_schedule", {"target_order_id": "RUSH-200"})
    drafts = invoke_tool(bound, "draft_communications", {"proposal_hash": proposal["content_hash"]})

    assert drafts["proposal_hash"] == proposal["content_hash"]
    assert [e.event_type for e in repository.audit_events()] == [
        "scenario_initialized",
        "proposal_created",
        "communications_drafted",
    ]


def test_invoke_tool_refuses_wrong_argument_names(tmp_path: Path) -> None:
    _, service = _service(tmp_path, with_catalog=False)
    bound = bind_shop_tools(service)
    with pytest.raises(TypeError, match="expects arguments"):
        invoke_tool(bound, "propose_schedule", {"order": "RUSH-200"})
    with pytest.raises(KeyError):
        spec_for("not_a_tool")
