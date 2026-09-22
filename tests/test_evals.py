"""Run the golden-set eval harness as part of the test suite."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
sys.path.insert(0, str(EVALS))

import run_evals


def test_golden_set_has_at_least_ten_cases_with_frozen_expectations() -> None:
    cases = run_evals.load_cases(run_evals.CASES_DIR)
    assert len(cases) >= 10
    for _, case in cases:
        assert case["expected"], case["id"]
        assert case["verdict"] in {"approve", "reject"}
        assert case["expects"] in {"proposal", "fail_closed"}
        assert case["customer_email"]


@pytest.mark.parametrize(
    "case",
    [case for _, case in run_evals.load_cases(run_evals.CASES_DIR)],
    ids=lambda case: case["id"],
)
def test_strands_and_langgraph_agree_on_each_case(case: dict) -> None:
    strands, langgraph = run_evals.evaluate(case)
    if case["expects"] == "fail_closed":
        assert strands.fail_closed_view() == langgraph.fail_closed_view() == case["expected"]
        assert langgraph.proposal_hash is None
        assert langgraph.final_revision == 1
        return
    assert strands.as_dict() == langgraph.as_dict()
    assert langgraph.as_dict() == case["expected"]
    assert langgraph.proposal_hash == case["expected"]["proposal_hash"]


def test_harness_exits_non_zero_on_a_mismatch(tmp_path: Path) -> None:
    source = run_evals.CASES_DIR / "01-rush-caps-approve.json"
    case = json.loads(source.read_text())
    case["expected"]["proposal_hash"] = "0" * 64
    (tmp_path / "tampered.json").write_text(json.dumps(case))

    result = subprocess.run(
        [sys.executable, str(EVALS / "run_evals.py"), "--cases", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "| FAIL |" in result.stdout
    assert "0/1 cases agree" in result.stdout


def test_harness_exits_zero_on_the_committed_golden_set() -> None:
    result = subprocess.run(
        [sys.executable, str(EVALS / "run_evals.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "| FAIL |" not in result.stdout
    assert result.stdout.count("| PASS |") >= 10
