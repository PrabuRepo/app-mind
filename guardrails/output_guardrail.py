"""
guardrails/output_guardrail.py — runs after synthesis/escalation, before the
answer reaches the user.

REAL CHECK: refuse to let a brief ship with zero citations (unless it's an
escalation brief, which is honest about having none) — replaces it with an
honest escalation brief instead of just warning and shipping it anyway. A
confident, uncited answer is exactly the false-confidence failure mode this
whole project exists to catch, so this guardrail must not let one through
even if every upstream node missed it. Also where the "no unresolved
critique flags" output rule would go.
"""

from __future__ import annotations

from app.schemas import DecisionBrief, GraphState


def output_guardrail(state: GraphState) -> dict:
    brief = state.decision_brief
    if brief and not brief.citations and "escalate" not in brief.answer.lower():
        print("[output_guardrail] BLOCKED: brief had zero citations — replacing with an honest escalation")
        safe_brief = DecisionBrief(
            answer="AppMind could not produce a properly cited answer to this question.",
            citations=[],
            confidence_rationale=(
                "output_guardrail blocked an uncited answer from shipping "
                "(zero citations, not an escalation)."
            ),
        )
        return {"decision_brief": safe_brief}
    print("[output_guardrail] passed")
    return {}
