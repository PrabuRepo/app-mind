"""
guardrails/input_guardrail.py — the first node in every run.

A guardrail's job is to catch bad input early and cheaply, before spending
any money on LLM calls or database queries for a question that was never
going to get a valid answer anyway.

STUBBED TODAY: always passes. Real version should reject obviously off-topic
questions and questions that look like they contain PII, per the "Handling
PII" line item on the evaluation rubric.

Also stamps `started_at` — the earliest point in the graph — so memory_write
(the last node) can compute a real `latency_ms` for the audit trail.
"""

from __future__ import annotations

import time

from app.schemas import GraphState


def input_guardrail(state: GraphState) -> dict:
    print(f"[input_guardrail] checking question: {state.question!r}")
    # In the real version, this node might set a field like
    # `state.blocked = True` and the graph would route straight to END.
    # For now every question passes through unchanged.
    return {"started_at": time.perf_counter()}
