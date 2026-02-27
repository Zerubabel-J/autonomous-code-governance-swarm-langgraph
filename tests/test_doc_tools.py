"""
Tests for src/tools/doc_tools.py — PDF forensic functions.

Tests use synthetic text fixtures — no real PDF required.
Pure-text functions (theoretical depth, path extraction, cross-reference) are
tested directly. PDF extraction functions are tested for graceful degradation.
"""

import pytest

from src.state import Evidence
from src.tools.doc_tools import (
    check_theoretical_depth,
    cross_reference_paths,
    extract_pdf_images,
    extract_pdf_text,
    find_mentioned_paths,
)


# ---------------------------------------------------------------------------
# check_theoretical_depth
# ---------------------------------------------------------------------------


def test_theoretical_depth_all_terms_substantive():
    """All theoretical terms present with substantive explanation."""
    text = (
        "Our architecture implements dialectical synthesis because the three judges "
        "converge through fan-in and fan-out patterns. The design ensures state synchronization "
        "via operator.ior reducers. Evidence aggregation implements a hard-block pattern. "
        "The adversarial posture pattern prevents persona collusion through distinct system prompts. "
        "The metacognition layer allows the system to evaluate its own evaluation."
    )
    result = check_theoretical_depth(text)
    assert len(result["terms_found"]) >= 5
    assert result["has_depth"] is True
    assert result["substantive_count"] >= 3


def test_theoretical_depth_no_terms():
    text = "This is a report about our code. We used Python and LangChain."
    result = check_theoretical_depth(text)
    assert len(result["terms_found"]) == 0
    assert len(result["terms_missing"]) == 8
    assert result["has_depth"] is False


def test_theoretical_depth_keyword_dropping():
    """Terms present but without substantive explanation markers."""
    text = (
        "Fan-in. Fan-out. Dialectical synthesis. Adversarial. "
        "Metacognition. State synchronization. Evidence aggregation. Persona collusion."
    )
    result = check_theoretical_depth(text)
    assert len(result["terms_found"]) == 8
    assert result["substantive_count"] < 3
    assert result["has_depth"] is False


def test_theoretical_depth_partial_terms_with_context():
    """Some terms present with explanation markers nearby."""
    text = (
        "We implement fan-out because the detectives run in parallel from START. "
        "Fan-in is the pattern where the aggregator collects all evidence. "
        "Our design ensures adversarial judges challenge each other."
    )
    result = check_theoretical_depth(text)
    assert "fan-out" in result["terms_found"]
    assert "fan-in" in result["terms_found"]
    assert "adversarial" in result["terms_found"]
    assert result["substantive_count"] >= 2


# ---------------------------------------------------------------------------
# find_mentioned_paths
# ---------------------------------------------------------------------------


def test_find_paths_extracts_src_files():
    text = "We implemented the state in src/state.py and the graph in src/graph.py."
    paths = find_mentioned_paths(text)
    assert "src/state.py" in paths
    assert "src/graph.py" in paths


def test_find_paths_extracts_nested_paths():
    text = "The judges are in src/nodes/judges.py and tools in src/tools/repo_tools.py."
    paths = find_mentioned_paths(text)
    assert "src/nodes/judges.py" in paths
    assert "src/tools/repo_tools.py" in paths


def test_find_paths_extracts_test_files():
    text = "Our test suite is in tests/test_graph.py and tests/test_rules.py."
    paths = find_mentioned_paths(text)
    assert "tests/test_graph.py" in paths
    assert "tests/test_rules.py" in paths


def test_find_paths_extracts_rubric_and_claude():
    text = "The rubric is defined in rubric.json. Instructions are in CLAUDE.md."
    paths = find_mentioned_paths(text)
    assert "rubric.json" in paths
    assert "CLAUDE.md" in paths


def test_find_paths_returns_empty_for_no_paths():
    text = "This report has no file references."
    paths = find_mentioned_paths(text)
    assert paths == []


def test_find_paths_deduplicates():
    text = "We use src/state.py for state. The state is in src/state.py."
    paths = find_mentioned_paths(text)
    assert paths.count("src/state.py") == 1


# ---------------------------------------------------------------------------
# cross_reference_paths
# ---------------------------------------------------------------------------


def test_cross_reference_all_verified():
    mentioned = ["src/state.py", "src/graph.py"]
    evidences = {
        "repo_investigator_state": [
            Evidence(goal="Check", found=True, location="src/state.py",
                     rationale="exists", confidence=1.0)
        ],
        "repo_investigator_graph": [
            Evidence(goal="Check", found=True, location="src/graph.py",
                     rationale="exists", confidence=1.0)
        ],
    }
    result = cross_reference_paths(mentioned, evidences)
    assert len(result["verified"]) == 2
    assert len(result["hallucinated"]) == 0
    assert result["accuracy_ratio"] == 1.0


def test_cross_reference_with_hallucinated_path():
    mentioned = ["src/state.py", "src/magic/unicorn.py"]
    evidences = {
        "repo_investigator_state": [
            Evidence(goal="Check", found=True, location="src/state.py",
                     rationale="exists", confidence=1.0)
        ],
    }
    result = cross_reference_paths(mentioned, evidences)
    assert "src/state.py" in result["verified"]
    assert "src/magic/unicorn.py" in result["hallucinated"]
    assert result["accuracy_ratio"] == 0.5


def test_cross_reference_empty_paths():
    result = cross_reference_paths([], {})
    assert result["verified"] == []
    assert result["hallucinated"] == []
    assert result["accuracy_ratio"] == 1.0


def test_cross_reference_ignores_not_found_evidence():
    """Evidence with found=False should not verify paths."""
    mentioned = ["src/state.py"]
    evidences = {
        "repo_investigator_state": [
            Evidence(goal="Check", found=False, location="N/A",
                     rationale="missing", confidence=1.0)
        ],
    }
    result = cross_reference_paths(mentioned, evidences)
    assert "src/state.py" in result["hallucinated"]


# ---------------------------------------------------------------------------
# extract_pdf_text / extract_pdf_images — graceful degradation
# ---------------------------------------------------------------------------


def test_extract_pdf_text_missing_file():
    result = extract_pdf_text("/nonexistent/path.pdf")
    assert result["error"] is not None
    assert result["text"] == ""
    assert result["page_count"] == 0


def test_extract_pdf_text_empty_path():
    result = extract_pdf_text("")
    assert result["error"] is not None


def test_extract_pdf_images_missing_file():
    result = extract_pdf_images("/nonexistent/path.pdf")
    assert result["error"] is not None
    assert result["images"] == []
    assert result["count"] == 0


def test_extract_pdf_images_empty_path():
    result = extract_pdf_images("")
    assert result["error"] is not None
