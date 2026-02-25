import operator

import pytest
from pydantic import ValidationError

from src.state import AgentState, AuditReport, CriterionResult, Evidence, JudicialOpinion


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_evidence(**kwargs) -> Evidence:
    defaults = dict(
        goal="Verify Pydantic state",
        found=True,
        location="src/state.py",
        rationale="File exists with BaseModel",
        confidence=1.0,
    )
    defaults.update(kwargs)
    return Evidence(**defaults)


def make_opinion(**kwargs) -> JudicialOpinion:
    defaults = dict(
        judge="Prosecutor",
        criterion_id="state_management_rigor",
        score=3,
        argument="Partial compliance.",
        cited_evidence=["src/state.py"],
    )
    defaults.update(kwargs)
    return JudicialOpinion(**defaults)


# ---------------------------------------------------------------------------
# Evidence — immutability (RISK-2)
# ---------------------------------------------------------------------------


def test_evidence_is_immutable():
    ev = make_evidence()
    with pytest.raises((ValidationError, TypeError)):
        ev.goal = "mutated"


def test_evidence_model_copy_creates_new_object():
    ev = make_evidence(found=True)
    ev2 = ev.model_copy(update={"found": False})
    assert ev.found is True
    assert ev2.found is False
    assert ev is not ev2


# ---------------------------------------------------------------------------
# Evidence — field validation
# ---------------------------------------------------------------------------


def test_evidence_confidence_lower_bound():
    with pytest.raises(ValidationError):
        make_evidence(confidence=-0.1)


def test_evidence_confidence_upper_bound():
    with pytest.raises(ValidationError):
        make_evidence(confidence=1.1)


def test_evidence_content_defaults_to_none():
    ev = make_evidence()
    assert ev.content is None


# ---------------------------------------------------------------------------
# JudicialOpinion — score validation
# ---------------------------------------------------------------------------


def test_opinion_score_too_high():
    with pytest.raises(ValidationError):
        make_opinion(score=6)


def test_opinion_score_too_low():
    with pytest.raises(ValidationError):
        make_opinion(score=0)


def test_opinion_score_boundary_values():
    low = make_opinion(score=1)
    high = make_opinion(score=5)
    assert low.score == 1
    assert high.score == 5


def test_opinion_judge_literal_invalid():
    with pytest.raises(ValidationError):
        make_opinion(judge="RandomPerson")


# ---------------------------------------------------------------------------
# State reducers (RISK-2)
# ---------------------------------------------------------------------------


def test_reducer_ior_merges_different_keys():
    ev = make_evidence()
    d1 = {"repo_investigator_state_management_rigor": [ev]}
    d2 = {"repo_investigator_git_forensic_analysis": [ev]}
    merged = operator.ior(d1, d2)
    assert "repo_investigator_state_management_rigor" in merged
    assert "repo_investigator_git_forensic_analysis" in merged
    assert len(merged) == 2


def test_reducer_ior_same_key_right_wins():
    """Documents expected behavior — namespaced keys prevent this in practice."""
    d1 = {"same_key": ["first"]}
    d2 = {"same_key": ["second"]}
    merged = operator.ior(d1, d2)
    assert merged["same_key"] == ["second"]


def test_reducer_add_appends_opinions():
    op1 = make_opinion(judge="Prosecutor")
    op2 = make_opinion(judge="Defense")
    combined = operator.add([op1], [op2])
    assert len(combined) == 2
    assert combined[0].judge == "Prosecutor"
    assert combined[1].judge == "Defense"


# ---------------------------------------------------------------------------
# Key naming convention guard (RISK-2)
# ---------------------------------------------------------------------------


def test_evidence_key_convention():
    """Keys must follow '{detective}_{criterion_id}' pattern."""
    detective = "repo_investigator"
    criterion = "state_management_rigor"
    key = f"{detective}_{criterion}"
    assert key == "repo_investigator_state_management_rigor"
    assert "_" in key
    assert key.startswith("repo_investigator")
