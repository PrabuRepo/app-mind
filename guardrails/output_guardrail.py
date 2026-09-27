"""
guardrails/output_guardrail.py — runs after synthesis/escalation, before the
answer reaches the user.

A concrete, checkable rule: refuse to let a brief ship with zero citations
(unless it's an escalation brief, which is honest about having none). Also
where the "no unresolved critique flags" output rule would go.

STUBBED TODAY: only logs a warning rather than actually blocking, since
blocking behavior needs a real decision about what happens next (retry?
hard-fail?) that's worth deciding deliberately, not by accident inside a stub.
"""

from __future__ import annotations

from app.schemas import GraphState


def output_guardrail(state: GraphState) -> dict:
    brief = state.decision_brief
    if brief and not brief.citations and "escalate" not in brief.answer.lower():
        print("[output_guardrail] WARNING: brief has zero citations (stub does not block yet)")
    else:
        print("[output_guardrail] passed")
    return {}
