"""
Deterministic conflict resolution rules for the Chief Justice.

RISK-1 MITIGATION: All rules are pure Python if/else logic.
No LLM calls exist in this module. Rules execute before any narrative
synthesis, anchoring scores deterministically.

Rule precedence (highest to lowest):
  1. Rule of Security   — confirmed security flaw caps score at 3
  2. Rule of Evidence   — detective facts override judge opinions
  3. Rule of Functionality — Tech Lead carries highest weight for graph_orchestration
  4. Dissent Requirement — variance > 2 mandates a dissent summary
"""

from typing import Dict, List, Optional

from src.state import Evidence, JudicialOpinion


# Keywords that constitute a confirmed security violation in Prosecutor arguments.
# Source: rubric.json synthesis_rules.security_override
_SECURITY_VIOLATION_KEYWORDS = [
    "os.system",
    "shell injection",
    "unsanitized input",
    "command injection",
    "security vulnerability",
    "security flaw",
    "security negligence",
]


# ---------------------------------------------------------------------------
# Rule 1: Security Override
# ---------------------------------------------------------------------------


def apply_security_rule(
    opinions: List[JudicialOpinion],
    evidences: Dict[str, List[Evidence]],
) -> Optional[int]:
    """
    Rule of Security: if the Prosecutor identified a confirmed security
    vulnerability — in their argument OR in detective evidence — cap score at 3.

    Returns the cap value (3) if triggered, else None.
    """
    # Check Prosecutor opinions first
    for opinion in opinions:
        if opinion.judge == "Prosecutor":
            if _contains_security_violation(opinion.argument):
                return 3

    # Check evidence rationale directly (facts override opinions — RISK-1)
    for ev_list in evidences.values():
        for ev in ev_list:
            if _contains_security_violation(ev.rationale):
                return 3

    return None


def _contains_security_violation(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in _SECURITY_VIOLATION_KEYWORDS)


# ---------------------------------------------------------------------------
# Rule 2: Fact Supremacy (Evidence Override)
# ---------------------------------------------------------------------------


def apply_evidence_rule(
    opinions: List[JudicialOpinion],
    evidences: Dict[str, List[Evidence]],
    criterion_id: str,
) -> List[JudicialOpinion]:
    """
    Rule of Evidence: overrule any Defense opinion whose cited_evidence
    locations are not backed by verified detective findings.

    A citation is invalid if no Evidence object with that location exists
    where found=True for the given criterion.
    """
    result = []
    for opinion in opinions:
        if opinion.judge == "Defense" and opinion.cited_evidence:
            for cited_loc in opinion.cited_evidence:
                if not _location_is_verified(evidences, criterion_id, cited_loc):
                    opinion = opinion.model_copy(update={
                        "score": 1,
                        "argument": (
                            f"[OVERRULED — FACT SUPREMACY] "
                            f"Cited location '{cited_loc}' not found in detective evidence. "
                            f"Original argument: {opinion.argument[:300]}"
                        ),
                    })
                    break
        result.append(opinion)
    return result


def _location_is_verified(
    evidences: Dict[str, List[Evidence]],
    criterion_id: str,
    location: str,
) -> bool:
    """Returns True if any Evidence object with found=True matches the location."""
    for key, ev_list in evidences.items():
        if criterion_id in key:
            for ev in ev_list:
                if ev.found and ev.location == location:
                    return True
    return False


# ---------------------------------------------------------------------------
# Rule 3: Functionality Weight
# ---------------------------------------------------------------------------


def compute_final_score(
    opinions: List[JudicialOpinion],
    criterion_id: str,
) -> int:
    """
    Rule of Functionality: for the graph_orchestration criterion, the Tech Lead's
    score carries 50% weight. For all other criteria, scores are averaged equally.

    Returns an integer score in [1, 5]. Returns 1 if opinions list is empty
    to avoid silent zero-scores.
    """
    if not opinions:
        return 1

    if criterion_id == "graph_orchestration":
        tl_opinions = [o for o in opinions if o.judge == "TechLead"]
        other_opinions = [o for o in opinions if o.judge != "TechLead"]
        if tl_opinions and other_opinions:
            tl_score = tl_opinions[0].score
            other_avg = sum(o.score for o in other_opinions) / len(other_opinions)
            weighted = tl_score * 0.5 + other_avg * 0.5
            return max(1, min(5, round(weighted)))

    avg = sum(o.score for o in opinions) / len(opinions)
    return max(1, min(5, round(avg)))


# ---------------------------------------------------------------------------
# Rule 4: Dissent Requirement
# ---------------------------------------------------------------------------


def check_dissent(opinions: List[JudicialOpinion]) -> Optional[str]:
    """
    Dissent Requirement: when score variance across judges exceeds 2,
    the Chief Justice MUST produce an explicit dissent summary.

    Returns a dissent string if triggered, else None.
    """
    if len(opinions) < 2:
        return None

    scores = [o.score for o in opinions]
    variance = max(scores) - min(scores)

    if variance > 2:
        breakdown = ", ".join(f"{o.judge}={o.score}" for o in opinions)
        high = max(opinions, key=lambda o: o.score)
        low = min(opinions, key=lambda o: o.score)
        return (
            f"Score variance of {variance} exceeds threshold of 2. "
            f"Breakdown: [{breakdown}]. "
            f"{high.judge} argued: '{high.argument[:150]}...' "
            f"{low.judge} countered: '{low.argument[:150]}...'"
        )

    return None
