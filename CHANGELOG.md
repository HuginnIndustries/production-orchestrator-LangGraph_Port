# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- LangGraph implementation of the governed loop (`langgraph_workflow.py`): a
  `StateGraph` with typed state, an `approval_gate` node that pauses on
  `langgraph.types.interrupt()`, a conditional route to a terminal `rejected`
  node, an `apply` node that re-runs the hash, revision, replay, identity, and
  provider-binding checks before the single write, and `SqliteSaver`
  persistence next to the shop database so a fresh process can resume.
- `production-orchestrator-langgraph-demo` CLI with `start` and
  `decide --approve|--reject --thread <id>` phases.
- `tool_specs.py`: the single framework-neutral definition of the eight tools,
  now consumed by both the Strands `@tool` surface and the LangGraph
  `StructuredTool` surface.
- Golden-set eval (`evals/cases/*.json`, `evals/run_evals.py`) that runs every
  case through both implementations and fails on any disagreement in proposal
  hash, tool sequence, audit chain, revision, or outcome; wired into CI and the
  test suite (`tests/test_evals.py`).
- `docs/LANGGRAPH_PORT.md` side-by-side comparison with known gaps.
- Dependencies: `langgraph`, `langgraph-checkpoint-sqlite`, `langchain-core`
  (pinned).

### Changed

- `workflow.build_strands_tools` now derives its tool list from `tool_specs`;
  names, descriptions, argument schemas, ordering, and catalog gating are
  unchanged.
- `persistence.proposal_from_payload` is exposed for rebuilding a proposal from
  its canonical dictionary form; `record_decision` returns the ledger row
  sequence and `ApprovalDecision` carries it.
- `approval.apply_production_plan` accepts an optional `expected_actor` and
  refuses an approval recorded by any other actor. Existing callers are
  unchanged.
- CI now also runs `ruff format --check` and the eval harness.
