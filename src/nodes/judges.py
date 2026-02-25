"""
Judicial layer — three-persona dialectical bench.

RISK-4 MITIGATION: Each persona has a distinct, conflicting system prompt.
Prompts share zero boilerplate text to prevent persona collusion.
Divergence is enforced structurally: each prompt instructs a different
analytical posture (adversarial / forgiving / pragmatic).

RISK-3 MITIGATION: _sanitize_for_judge() strips Evidence.content entirely.
Judges receive only structured metadata fields.

RISK-1 MITIGATION: Judges produce raw opinions only. No scoring logic here.
All score resolution happens in ChiefJustice via deterministic rules.

Phase 1 scope: Prosecutor only. Defense and TechLead nodes are present
but raise NotImplementedError until Phase 3.
"""

import json
from pathlib import Path
from typing import List

from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from src.state import AgentState, Evidence, JudicialOpinion

# ---------------------------------------------------------------------------
# Rubric loading — loaded once at module import, never hardcoded in prompts
# ---------------------------------------------------------------------------

_RUBRIC_PATH = Path(__file__).parent.parent.parent / "rubric.json"
_RUBRIC: dict = json.loads(_RUBRIC_PATH.read_text(encoding="utf-8"))
_DIMENSIONS_BY_ID: dict[str, dict] = {
    d["id"]: d for d in _RUBRIC["dimensions"]
}

# ---------------------------------------------------------------------------
# Shared LLM factory — model name in one place
# ---------------------------------------------------------------------------

_MODEL = "gemini-2.0-flash"


def _make_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(model=_MODEL, temperature=0.2)


# ---------------------------------------------------------------------------
# Evidence sanitizer — RISK-3 guard
# ---------------------------------------------------------------------------


def _sanitize_for_judge(evidences: List[Evidence]) -> str:
    """
    Convert Evidence objects to a plain-text summary for judge context.
    Evidence.content is explicitly excluded — judges never see raw code.
    Only structured metadata is passed: goal, found, location, confidence, rationale.
    """
    if not evidences:
        return "No evidence collected for this criterion."
    lines = []
    for ev in evidences:
        lines.append(
            f"- goal: {ev.goal}\n"
            f"  found: {ev.found}\n"
            f"  location: {ev.location}\n"
            f"  confidence: {ev.confidence:.2f}\n"
            f"  rationale: {ev.rationale}"
        )
    return "\n".join(lines)


def _get_criterion_rubric(criterion_id: str) -> str:
    """Load success/failure patterns from rubric.json — never hardcode criteria."""
    dim = _DIMENSIONS_BY_ID.get(criterion_id)
    if not dim:
        return f"No rubric entry found for criterion: {criterion_id}"
    return (
        f"Criterion: {dim['name']}\n"
        f"Success pattern: {dim['success_pattern']}\n"
        f"Failure pattern: {dim['failure_pattern']}"
    )


# ---------------------------------------------------------------------------
# Prosecutor Node
# ---------------------------------------------------------------------------

# RISK-4: This prompt is intentionally adversarial and shares NO text with
# the Defense or TechLead prompts. Its posture is suspicion by default.
_PROSECUTOR_SYSTEM = """You are The Prosecutor in a forensic code audit. Your mandate is adversarial.

Your philosophy: "Trust No One. Assume Vibe Coding. Every gap is intentional laziness until proven otherwise."

Your analytical rules — follow these exactly:
- State file missing entirely: score MUST be 1. No exceptions.
- Typed state exists but reducers absent: score MUST be 2 or 3.
- os.system() call confirmed: score MUST be 1 for safe_tool_engineering.
- Bulk upload git history (1-2 commits): score MUST be 1 or 2.
- Freeform judge output (no structured output): score MUST be 1 for structured_output_enforcement.
- Only award score 4 or 5 if evidence EXPLICITLY confirms full compliance.
- cited_evidence MUST contain the Evidence location strings. Do not invent file paths.
- If evidence rationale mentions "violation" or "not found": argue for the lowest defensible score.

Return a JudicialOpinion with judge="Prosecutor". No prose outside the structured fields."""


def prosecutor_node(state: AgentState) -> dict:
    """
    The Prosecutor evaluates all 5 repo-targeted criteria independently.
    Returns one JudicialOpinion per criterion.
    """
    evidences = state.get("evidences", {})
    opinions = []

    repo_criteria = [
        "git_forensic_analysis",
        "state_management_rigor",
        "graph_orchestration",
        "safe_tool_engineering",
        "structured_output_enforcement",
    ]

    llm = _make_llm()
    structured_llm = llm.with_structured_output(JudicialOpinion)

    prompt = ChatPromptTemplate.from_messages([
        ("system", _PROSECUTOR_SYSTEM),
        ("human", (
            "{rubric_standard}\n\n"
            "Evidence collected by the detective:\n"
            "{evidence_summary}\n\n"
            "Return your JudicialOpinion.\n"
            "Set judge=\"Prosecutor\" and criterion_id=\"{criterion_id}\"."
        )),
    ])

    chain = prompt | structured_llm

    for criterion_id in repo_criteria:
        evidence_key = f"repo_investigator_{criterion_id}"
        raw_evidences = evidences.get(evidence_key, [])
        evidence_summary = _sanitize_for_judge(raw_evidences)
        rubric_standard = _get_criterion_rubric(criterion_id)

        try:
            opinion: JudicialOpinion = chain.invoke({
                "criterion_id": criterion_id,
                "rubric_standard": rubric_standard,
                "evidence_summary": evidence_summary,
            })
            # Enforce correct judge label regardless of LLM output
            if opinion.judge != "Prosecutor":
                opinion = opinion.model_copy(update={"judge": "Prosecutor"})
            opinions.append(opinion)

        except Exception as exc:
            # RISK-5: Never crash the graph. Return a minimal opinion on failure.
            opinions.append(JudicialOpinion(
                judge="Prosecutor",
                criterion_id=criterion_id,
                score=1,
                argument=f"[PROSECUTOR ERROR] Structured output failed: {str(exc)[:200]}",
                cited_evidence=[],
            ))

    return {"opinions": opinions}


# ---------------------------------------------------------------------------
# Defense Attorney Node (Phase 3)
# ---------------------------------------------------------------------------

# RISK-4: This prompt rewards effort and is explicitly forgiving.
# Shares zero text with Prosecutor or TechLead.
_DEFENSE_SYSTEM = """You are the Defense Attorney in a forensic code audit. Your mandate is to advocate for the developer.

Your philosophy: "Reward effort and intent. Look for the spirit of the law, not just the letter."

Your analytical rules — follow these exactly:
- Broken graph topology but sophisticated AST logic: argue for score 3 minimum.
- Bulk git history but strong implementation quality: argue the code quality overrides process gaps.
- Missing reducers but correct Pydantic models: partial credit, score 3 or 4.
- cited_evidence MUST contain real Evidence location strings from the detective findings.
- If evidence shows genuine effort or deep understanding, reward it even if execution was imperfect.
- Only assign score 1 if the evidence shows total absence of the feature with no compensating effort.

Return a JudicialOpinion with judge="Defense". No prose outside the structured fields."""


def defense_node(state: AgentState) -> dict:
    """Defense Attorney — evaluates all 5 repo-targeted criteria."""
    evidences = state.get("evidences", {})
    opinions = []

    repo_criteria = [
        "git_forensic_analysis",
        "state_management_rigor",
        "graph_orchestration",
        "safe_tool_engineering",
        "structured_output_enforcement",
    ]

    llm = _make_llm()
    structured_llm = llm.with_structured_output(JudicialOpinion)

    prompt = ChatPromptTemplate.from_messages([
        ("system", _DEFENSE_SYSTEM),
        ("human", (
            "{rubric_standard}\n\n"
            "Evidence collected by the detective:\n"
            "{evidence_summary}\n\n"
            "Return your JudicialOpinion.\n"
            "Set judge=\"Defense\" and criterion_id=\"{criterion_id}\"."
        )),
    ])

    chain = prompt | structured_llm

    for criterion_id in repo_criteria:
        evidence_key = f"repo_investigator_{criterion_id}"
        raw_evidences = evidences.get(evidence_key, [])
        evidence_summary = _sanitize_for_judge(raw_evidences)
        rubric_standard = _get_criterion_rubric(criterion_id)

        try:
            opinion: JudicialOpinion = chain.invoke({
                "criterion_id": criterion_id,
                "rubric_standard": rubric_standard,
                "evidence_summary": evidence_summary,
            })
            if opinion.judge != "Defense":
                opinion = opinion.model_copy(update={"judge": "Defense"})
            opinions.append(opinion)

        except Exception as exc:
            opinions.append(JudicialOpinion(
                judge="Defense",
                criterion_id=criterion_id,
                score=3,
                argument=f"[DEFENSE ERROR] Structured output failed: {str(exc)[:200]}",
                cited_evidence=[],
            ))

    return {"opinions": opinions}


# ---------------------------------------------------------------------------
# Tech Lead Node (Phase 3)
# ---------------------------------------------------------------------------

# RISK-4: This prompt is pragmatic and implementation-focused.
# Shares zero text with Prosecutor or Defense.
_TECHLEAD_SYSTEM = """You are the Tech Lead in a forensic code audit. Your mandate is technical objectivity.

Your philosophy: "Does it actually work? Is it maintainable? Ignore the struggle, judge the artifact."

Your analytical rules — follow these exactly:
- Evaluate only what the evidence shows exists — not what the developer intended.
- Pydantic models without reducers: score 3 (works but will break under parallel writes).
- subprocess.run with tempfile: score 4 or 5 for safe_tool_engineering.
- os.system() confirmed: score 1, cite "Security Negligence" as the ruling.
- Linear StateGraph (no fan-out): score 2, cite "Orchestration Bottleneck".
- with_structured_output bound to JudicialOpinion: score 4 or 5.
- cited_evidence MUST reference specific Evidence location strings.
- Tie-breaker role: your score carries highest weight for graph_orchestration criterion.

Return a JudicialOpinion with judge="TechLead". No prose outside the structured fields."""


def techlead_node(state: AgentState) -> dict:
    """Tech Lead — evaluates all 5 repo-targeted criteria."""
    evidences = state.get("evidences", {})
    opinions = []

    repo_criteria = [
        "git_forensic_analysis",
        "state_management_rigor",
        "graph_orchestration",
        "safe_tool_engineering",
        "structured_output_enforcement",
    ]

    llm = _make_llm()
    structured_llm = llm.with_structured_output(JudicialOpinion)

    prompt = ChatPromptTemplate.from_messages([
        ("system", _TECHLEAD_SYSTEM),
        ("human", (
            "{rubric_standard}\n\n"
            "Evidence collected by the detective:\n"
            "{evidence_summary}\n\n"
            "Return your JudicialOpinion.\n"
            "Set judge=\"TechLead\" and criterion_id=\"{criterion_id}\"."
        )),
    ])

    chain = prompt | structured_llm

    for criterion_id in repo_criteria:
        evidence_key = f"repo_investigator_{criterion_id}"
        raw_evidences = evidences.get(evidence_key, [])
        evidence_summary = _sanitize_for_judge(raw_evidences)
        rubric_standard = _get_criterion_rubric(criterion_id)

        try:
            opinion: JudicialOpinion = chain.invoke({
                "criterion_id": criterion_id,
                "rubric_standard": rubric_standard,
                "evidence_summary": evidence_summary,
            })
            if opinion.judge != "TechLead":
                opinion = opinion.model_copy(update={"judge": "TechLead"})
            opinions.append(opinion)

        except Exception as exc:
            opinions.append(JudicialOpinion(
                judge="TechLead",
                criterion_id=criterion_id,
                score=2,
                argument=f"[TECHLEAD ERROR] Structured output failed: {str(exc)[:200]}",
                cited_evidence=[],
            ))

    return {"opinions": opinions}
