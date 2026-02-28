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

All three judges run in parallel. Each evaluates every criterion
that has collected evidence — both repo and PDF criteria.
"""

import json
import time
from pathlib import Path
from typing import List

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

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

_MODEL = "gpt-4o-mini"


def _make_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=_MODEL,
        temperature=0.0,
    )


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


def _collect_evidence_for_criterion(
    evidences: dict, criterion_id: str,
) -> list:
    """Collect evidence from ALL detectives for a given criterion_id."""
    all_ev = []
    for key, ev_list in evidences.items():
        if key.endswith(f"_{criterion_id}"):
            all_ev.extend(ev_list)
    return all_ev


def _find_evaluated_criteria(evidences: dict) -> list[str]:
    """Discover all unique criterion IDs from available evidence keys."""
    criteria = set()
    for key in evidences:
        # Keys are "{detective}_{criterion_id}" — split from the right is unreliable
        # Instead, check against known rubric dimension IDs
        for dim_id in _DIMENSIONS_BY_ID:
            if key.endswith(f"_{dim_id}"):
                criteria.add(dim_id)
                break
    return sorted(criteria)


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
    The Prosecutor evaluates ALL criteria that have collected evidence.
    Returns one JudicialOpinion per criterion.
    """
    return _run_judge(state, "Prosecutor", _PROSECUTOR_SYSTEM, fallback_score=1)


def _run_judge(
    state: AgentState,
    judge_name: str,
    system_prompt: str,
    fallback_score: int,
) -> dict:
    """Shared judge runner — evaluates all criteria with evidence."""
    evidences = state.get("evidences", {})
    criteria = _find_evaluated_criteria(evidences)
    opinions = []

    llm = _make_llm()
    structured_llm = llm.with_structured_output(JudicialOpinion)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", (
            "{rubric_standard}\n\n"
            "Evidence collected by the detective:\n"
            "{evidence_summary}\n\n"
            "Return your JudicialOpinion.\n"
            "Set judge=\"{judge_name}\" and criterion_id=\"{criterion_id}\"."
        )),
    ])

    chain = prompt | structured_llm

    for criterion_id in criteria:
        raw_evidences = _collect_evidence_for_criterion(evidences, criterion_id)
        evidence_summary = _sanitize_for_judge(raw_evidences)
        rubric_standard = _get_criterion_rubric(criterion_id)

        inputs = {
            "criterion_id": criterion_id,
            "rubric_standard": rubric_standard,
            "evidence_summary": evidence_summary,
            "judge_name": judge_name,
        }

        # Retry loop: 2 attempts with back-off to handle transient API errors.
        # Structured output must parse to JudicialOpinion — if it fails, retry once.
        last_exc = None
        for attempt in range(2):
            try:
                opinion: JudicialOpinion = chain.invoke(inputs)
                if opinion.judge != judge_name:
                    opinion = opinion.model_copy(update={"judge": judge_name})
                opinions.append(opinion)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt == 0:
                    time.sleep(2)  # brief wait before retry

        if last_exc is not None:
            opinions.append(JudicialOpinion(
                judge=judge_name,
                criterion_id=criterion_id,
                score=fallback_score,
                argument=f"[{judge_name.upper()} ERROR] Structured output failed after 2 attempts: {str(last_exc)[:200]}",
                cited_evidence=[],
            ))

        # No rate limiting needed for local Ollama inference
        pass

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
    """Defense Attorney — evaluates all criteria with available evidence."""
    return _run_judge(state, "Defense", _DEFENSE_SYSTEM, fallback_score=3)


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
    """Tech Lead — evaluates all criteria with available evidence."""
    return _run_judge(state, "TechLead", _TECHLEAD_SYSTEM, fallback_score=2)
