import pytest

from src.rules import (
    apply_evidence_rule,
    apply_security_rule,
    check_dissent,
    compute_final_score,
)
from src.state import Evidence, JudicialOpinion


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_evidence(found=True, location="src/state.py", rationale="exists") -> Evidence:
    return Evidence(
        goal="test",
        found=found,
        location=location,
        rationale=rationale,
        confidence=1.0,
    )


def make_opinion(judge="Prosecutor", score=3, argument="test", cited=None) -> JudicialOpinion:
    return JudicialOpinion(
        judge=judge,
        criterion_id="state_management_rigor",
        score=score,
        argument=argument,
        cited_evidence=cited or [],
    )


# ---------------------------------------------------------------------------
# Rule 1: Security Override
# ---------------------------------------------------------------------------


def test_security_rule_triggers_on_os_system_in_evidence_rationale():
    """Ground truth: forensic evidence rationale triggers the security cap."""
    ev = make_evidence(rationale="os.system call detected in clone function")
    cap = apply_security_rule([], {"repo_investigator_safe_tool_engineering": [ev]})
    assert cap == 3


def test_security_rule_triggers_on_shell_injection_in_evidence():
    """Shell injection keyword in evidence rationale triggers the cap."""
    ev = make_evidence(rationale="shell injection risk detected via AST analysis")
    cap = apply_security_rule([], {"repo_investigator_safe_tool_engineering": [ev]})
    assert cap == 3


def test_security_rule_does_not_trigger_on_opinion_argument():
    """LLM opinion arguments must NOT trigger the security cap.
    Adversarial judges may mention 'os.system' in negative/hypothetical context."""
    opinion = make_opinion(judge="Prosecutor", argument="Found raw os.system call in repo_tools.py")
    cap = apply_security_rule([opinion], {})
    assert cap is None


def test_security_rule_does_not_trigger_on_negative_mention_in_opinion():
    """False positive guard: 'os.system() calls are not present' must not cap score."""
    opinion = make_opinion(judge="Prosecutor", argument="Raw os.system() calls are not present.")
    cap = apply_security_rule([opinion], {})
    assert cap is None


def test_security_rule_does_not_trigger_on_clean_evidence():
    ev = make_evidence(rationale="subprocess.run with tempfile.TemporaryDirectory used correctly")
    cap = apply_security_rule([], {"repo_investigator_safe_tool_engineering": [ev]})
    assert cap is None


def test_security_rule_ignores_all_opinion_arguments():
    """Security rule does not inspect any opinion arguments — only evidence rationale."""
    opinions = [
        make_opinion(judge="Prosecutor", argument="os.system detected — critical violation"),
        make_opinion(judge="Defense", argument="shell injection risk but developer tried"),
    ]
    cap = apply_security_rule(opinions, {})
    assert cap is None


def test_security_rule_is_case_insensitive_in_evidence():
    ev = make_evidence(rationale="OS.SYSTEM CALL DETECTED")
    cap = apply_security_rule([], {"key": [ev]})
    assert cap == 3


# ---------------------------------------------------------------------------
# Rule 2: Evidence Override (Fact Supremacy)
# ---------------------------------------------------------------------------


def test_evidence_rule_overrules_defense_citing_missing_location():
    opinion = make_opinion(judge="Defense", score=5, cited=["src/nodes/judges.py"])
    # No evidence confirms this location exists
    result = apply_evidence_rule([opinion], {}, "state_management_rigor")
    assert result[0].score == 1
    assert "OVERRULED" in result[0].argument


def test_evidence_rule_preserves_defense_citing_verified_location():
    ev = make_evidence(found=True, location="src/state.py")
    opinion = make_opinion(judge="Defense", score=4, cited=["src/state.py"])
    result = apply_evidence_rule(
        [opinion],
        {"repo_investigator_state_management_rigor": [ev]},
        "state_management_rigor",
    )
    assert result[0].score == 4
    assert "OVERRULED" not in result[0].argument


def test_evidence_rule_does_not_affect_prosecutor():
    opinion = make_opinion(judge="Prosecutor", score=1, cited=["nonexistent/path.py"])
    result = apply_evidence_rule([opinion], {}, "state_management_rigor")
    assert result[0].score == 1
    assert "OVERRULED" not in result[0].argument


def test_evidence_rule_does_not_affect_techlead():
    opinion = make_opinion(judge="TechLead", score=2, cited=["ghost/file.py"])
    result = apply_evidence_rule([opinion], {}, "state_management_rigor")
    assert result[0].score == 2


def test_evidence_rule_skips_defense_with_no_citations():
    opinion = make_opinion(judge="Defense", score=4, cited=[])
    result = apply_evidence_rule([opinion], {}, "state_management_rigor")
    assert result[0].score == 4


# ---------------------------------------------------------------------------
# Rule 3: Functionality Weight
# ---------------------------------------------------------------------------


def test_score_averages_equally_for_non_orchestration_criterion():
    opinions = [
        make_opinion(judge="Prosecutor", score=1),
        make_opinion(judge="Defense", score=5),
    ]
    score = compute_final_score(opinions, "state_management_rigor")
    assert score == 3


def test_score_techlead_gets_50_percent_for_graph_orchestration():
    opinions = [
        JudicialOpinion(judge="TechLead", criterion_id="graph_orchestration", score=2, argument="bad", cited_evidence=[]),
        JudicialOpinion(judge="Prosecutor", criterion_id="graph_orchestration", score=4, argument="ok", cited_evidence=[]),
    ]
    score = compute_final_score(opinions, "graph_orchestration")
    # TechLead=2 (50%) + Prosecutor=4 (50%) = 3.0 -> rounds to 3
    assert score == 3


def test_score_returns_1_for_empty_opinions():
    assert compute_final_score([], "state_management_rigor") == 1


def test_score_clamps_to_valid_range():
    opinions = [make_opinion(score=5), make_opinion(score=5)]
    score = compute_final_score(opinions, "state_management_rigor")
    assert 1 <= score <= 5


# ---------------------------------------------------------------------------
# Rule 4: Dissent Requirement
# ---------------------------------------------------------------------------


def test_dissent_triggers_when_variance_exceeds_2():
    opinions = [
        make_opinion(judge="Prosecutor", score=1, argument="Completely broken."),
        make_opinion(judge="Defense", score=5, argument="Outstanding effort."),
    ]
    dissent = check_dissent(opinions)
    assert dissent is not None
    assert "variance" in dissent.lower()


def test_dissent_does_not_trigger_for_variance_of_2():
    opinions = [
        make_opinion(judge="Prosecutor", score=2),
        make_opinion(judge="Defense", score=4),
    ]
    dissent = check_dissent(opinions)
    assert dissent is None


def test_dissent_does_not_trigger_for_single_opinion():
    opinions = [make_opinion(score=3)]
    dissent = check_dissent(opinions)
    assert dissent is None


def test_dissent_contains_score_breakdown():
    opinions = [
        make_opinion(judge="Prosecutor", score=1, argument="Broken."),
        make_opinion(judge="Defense", score=5, argument="Great."),
    ]
    dissent = check_dissent(opinions)
    assert "Prosecutor=1" in dissent
    assert "Defense=5" in dissent
