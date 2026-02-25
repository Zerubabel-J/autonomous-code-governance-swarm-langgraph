"""
Graph topology and integration tests.

All tests use mocked nodes — no real repo cloning or LLM calls.
Tests verify: graph compiles, topology is correct, state flows end-to-end,
final_report is populated, and Markdown output is structurally valid.
"""

from unittest.mock import patch

import pytest

from src.graph import build_graph, run_audit
from src.nodes.justice import render_markdown_report
from src.state import AgentState, AuditReport, CriterionResult, Evidence, JudicialOpinion


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_evidence(criterion_id: str, found: bool = True) -> Evidence:
    return Evidence(
        goal=f"Check {criterion_id}",
        found=found,
        location="src/state.py" if found else "N/A",
        rationale="Synthetic evidence for test",
        confidence=1.0,
    )


def make_opinion(criterion_id: str, judge: str = "Prosecutor", score: int = 3) -> JudicialOpinion:
    return JudicialOpinion(
        judge=judge,
        criterion_id=criterion_id,
        score=score,
        argument=f"Synthetic argument for {criterion_id}",
        cited_evidence=[],
    )


_REPO_CRITERIA = [
    "git_forensic_analysis",
    "state_management_rigor",
    "graph_orchestration",
    "safe_tool_engineering",
    "structured_output_enforcement",
]


def make_full_evidences() -> dict:
    return {
        f"repo_investigator_{cid}": [make_evidence(cid)]
        for cid in _REPO_CRITERIA
    }


def make_full_opinions(score: int = 3) -> list:
    return [make_opinion(cid, score=score) for cid in _REPO_CRITERIA]


# ---------------------------------------------------------------------------
# Graph topology tests
# ---------------------------------------------------------------------------


def test_linear_graph_compiles():
    graph = build_graph(parallel=False)
    assert graph is not None


def test_parallel_graph_compiles():
    graph = build_graph(parallel=True)
    assert graph is not None


def test_linear_graph_has_required_nodes():
    graph = build_graph(parallel=False)
    nodes = set(graph.nodes)
    for required in ["repo_investigator", "evidence_aggregator", "prosecutor", "chief_justice"]:
        assert required in nodes, f"Missing node: {required}"


def test_parallel_graph_has_all_judge_nodes():
    graph = build_graph(parallel=True)
    nodes = set(graph.nodes)
    for required in ["prosecutor", "defense", "techlead"]:
        assert required in nodes, f"Missing judge node: {required}"


# ---------------------------------------------------------------------------
# EvidenceAggregator tests
# ---------------------------------------------------------------------------


def test_aggregator_passes_with_complete_evidence():
    from src.nodes.justice import evidence_aggregator_node

    state: AgentState = {
        "repo_url": "https://github.com/test/repo",
        "pdf_path": "",
        "rubric_dimensions": [],
        "evidences": make_full_evidences(),
        "opinions": [],
        "final_report": None,
    }
    result = evidence_aggregator_node(state)
    assert result == {}


def test_aggregator_raises_on_missing_evidence_key():
    from src.nodes.justice import evidence_aggregator_node

    incomplete = make_full_evidences()
    del incomplete["repo_investigator_state_management_rigor"]

    state: AgentState = {
        "repo_url": "https://github.com/test/repo",
        "pdf_path": "",
        "rubric_dimensions": [],
        "evidences": incomplete,
        "opinions": [],
        "final_report": None,
    }
    with pytest.raises(ValueError, match="missing evidence keys"):
        evidence_aggregator_node(state)


def test_aggregator_raises_on_empty_evidences():
    from src.nodes.justice import evidence_aggregator_node

    state: AgentState = {
        "repo_url": "https://github.com/test/repo",
        "pdf_path": "",
        "rubric_dimensions": [],
        "evidences": {},
        "opinions": [],
        "final_report": None,
    }
    with pytest.raises(ValueError):
        evidence_aggregator_node(state)


# ---------------------------------------------------------------------------
# ChiefJustice deterministic rule tests
# ---------------------------------------------------------------------------


def test_chief_justice_produces_report():
    from src.nodes.justice import chief_justice_node

    state: AgentState = {
        "repo_url": "https://github.com/test/repo",
        "pdf_path": "",
        "rubric_dimensions": [],
        "evidences": make_full_evidences(),
        "opinions": make_full_opinions(score=3),
        "final_report": None,
    }
    result = chief_justice_node(state)
    assert result["final_report"] is not None
    report = result["final_report"]
    assert 1.0 <= report.overall_score <= 5.0
    assert len(report.criteria) == 5


def test_chief_justice_score_cap_on_security_violation():
    from src.nodes.justice import chief_justice_node

    # Prosecutor flags os.system — score must be capped at 3
    opinions_with_violation = [
        JudicialOpinion(
            judge="Prosecutor",
            criterion_id="safe_tool_engineering",
            score=5,  # Would be high without rule
            argument="os.system() call detected — security violation",
            cited_evidence=[],
        )
    ] + [make_opinion(cid) for cid in _REPO_CRITERIA if cid != "safe_tool_engineering"]

    state: AgentState = {
        "repo_url": "https://github.com/test/repo",
        "pdf_path": "",
        "rubric_dimensions": [],
        "evidences": make_full_evidences(),
        "opinions": opinions_with_violation,
        "final_report": None,
    }
    result = chief_justice_node(state)
    report = result["final_report"]

    safe_tool = next(c for c in report.criteria if c.dimension_id == "safe_tool_engineering")
    assert safe_tool.final_score <= 3, "Security rule did not cap score"


def test_chief_justice_dissent_triggered_on_high_variance():
    from src.nodes.justice import chief_justice_node

    high_variance_opinions = [
        JudicialOpinion(
            judge="Prosecutor",
            criterion_id="state_management_rigor",
            score=1,
            argument="Complete failure.",
            cited_evidence=[],
        ),
        JudicialOpinion(
            judge="Defense",
            criterion_id="state_management_rigor",
            score=5,
            argument="Outstanding effort.",
            cited_evidence=[],
        ),
    ] + [make_opinion(cid) for cid in _REPO_CRITERIA if cid != "state_management_rigor"]

    state: AgentState = {
        "repo_url": "https://github.com/test/repo",
        "pdf_path": "",
        "rubric_dimensions": [],
        "evidences": make_full_evidences(),
        "opinions": high_variance_opinions,
        "final_report": None,
    }
    result = chief_justice_node(state)
    report = result["final_report"]
    state_mgmt = next(c for c in report.criteria if c.dimension_id == "state_management_rigor")
    assert state_mgmt.dissent_summary is not None, "Dissent not triggered for variance > 2"


# ---------------------------------------------------------------------------
# Markdown render tests
# ---------------------------------------------------------------------------


def test_markdown_contains_required_sections():
    criterion = CriterionResult(
        dimension_id="state_management_rigor",
        dimension_name="State Management Rigor",
        final_score=3,
        judge_opinions=[make_opinion("state_management_rigor")],
        remediation="Fix reducers.",
    )
    report = AuditReport(
        repo_url="https://github.com/test/repo",
        executive_summary="Test summary.",
        overall_score=3.0,
        criteria=[criterion],
        remediation_plan="Fix reducers.",
    )
    md = render_markdown_report(report)
    assert "## Executive Summary" in md
    assert "## Criterion Breakdown" in md
    assert "## Remediation Plan" in md
    assert "State Management Rigor" in md
    assert "**Final Score:** 3 / 5" in md


def test_markdown_includes_dissent_when_present():
    criterion = CriterionResult(
        dimension_id="graph_orchestration",
        dimension_name="Graph Orchestration",
        final_score=2,
        judge_opinions=[make_opinion("graph_orchestration")],
        dissent_summary="Prosecutor and Defense disagreed significantly.",
        remediation="Implement parallel fan-out.",
    )
    report = AuditReport(
        repo_url="https://github.com/test/repo",
        executive_summary="Test.",
        overall_score=2.0,
        criteria=[criterion],
        remediation_plan="Fix graph.",
    )
    md = render_markdown_report(report)
    assert "**Dissent:**" in md
    assert "Prosecutor and Defense disagreed" in md


def test_markdown_no_dissent_section_when_absent():
    criterion = CriterionResult(
        dimension_id="safe_tool_engineering",
        dimension_name="Safe Tool Engineering",
        final_score=4,
        judge_opinions=[make_opinion("safe_tool_engineering")],
        dissent_summary=None,
        remediation="Looks good.",
    )
    report = AuditReport(
        repo_url="https://github.com/test/repo",
        executive_summary="Test.",
        overall_score=4.0,
        criteria=[criterion],
        remediation_plan="No issues.",
    )
    md = render_markdown_report(report)
    assert "**Dissent:**" not in md


# ---------------------------------------------------------------------------
# End-to-end synthetic pipeline test
# ---------------------------------------------------------------------------


@patch("src.nodes.judges.ChatPromptTemplate")
@patch("src.nodes.judges._make_llm")
@patch("src.nodes.detectives.clone_repo_sandboxed")
@patch("src.nodes.detectives.extract_git_history")
@patch("src.nodes.detectives.check_state_management_rigor")
@patch("src.nodes.detectives.check_graph_orchestration")
@patch("src.nodes.detectives.check_safe_tool_engineering")
@patch("src.nodes.detectives.check_structured_output_enforcement")
def test_end_to_end_synthetic_pipeline(
    mock_structured, mock_safe, mock_graph, mock_state,
    mock_git, mock_clone, mock_make_llm, mock_prompt_cls,
):
    """Full pipeline: repo_investigator → aggregator → prosecutor → chief_justice."""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    # Mock clone
    tmpdir = TemporaryDirectory()
    mock_clone.return_value = (tmpdir, Path(tmpdir.name))

    # Mock tool results
    mock_git.return_value = {"commits": ["abc init"], "total_count": 1, "has_progression": False, "is_bulk_upload": True, "error": None}
    mock_state.return_value = {"found": True, "location": "src/state.py", "parse_error": None, "has_basemodel": True, "has_typeddict": True, "has_reducers": True}
    mock_graph.return_value = {"found": True, "location": "src/graph.py", "parse_error": None, "has_stategraph": True, "has_fan_out": True, "has_aggregator": True, "edge_count": 6}
    mock_safe.return_value = {"found": True, "location": "src/tools/", "uses_tempfile": True, "uses_subprocess": True, "has_os_system": False, "parse_error": None}
    mock_structured.return_value = {"found": True, "location": "src/nodes/judges.py", "has_structured_output": True, "has_judicial_opinion_binding": True, "parse_error": None}

    # Mock LLM chain
    def invoke_fn(inputs):
        return JudicialOpinion(
            judge="Prosecutor",
            criterion_id=inputs["criterion_id"],
            score=3,
            argument=f"Synthetic verdict for {inputs['criterion_id']}",
            cited_evidence=[],
        )

    mock_prompt = mock_prompt_cls.from_messages.return_value
    mock_prompt.__or__ = lambda self, other: type("Chain", (), {"invoke": staticmethod(invoke_fn)})()
    mock_make_llm.return_value.__class__ = object

    graph = build_graph(parallel=False)
    import json
    rubric = json.loads((Path("rubric.json")).read_text())

    initial_state: AgentState = {
        "repo_url": "https://github.com/synthetic/test",
        "pdf_path": "",
        "rubric_dimensions": rubric["dimensions"],
        "evidences": {},
        "opinions": [],
        "final_report": None,
    }

    final_state = graph.invoke(initial_state)

    assert final_state["final_report"] is not None
    report = final_state["final_report"]
    assert 1.0 <= report.overall_score <= 5.0
    assert len(report.criteria) == 5
    assert len(final_state["opinions"]) == 5
    assert all(k.startswith("repo_investigator_") for k in final_state["evidences"])
