"""
guardrails/input_guardrail.py — the first node in every run.

A guardrail's job is to catch bad input early and cheaply, before spending
any money on LLM calls or database queries for a question that was never
going to get a valid answer anyway.

REAL CHECK: rejects a question that looks like it contains PII (an email
address, phone number, or SSN-like pattern) — plain regex, no LLM call,
deliberately deterministic and cheap, matching the whole point of an input
guardrail. Off-topic questions are NOT filtered here: the existing
empty-retrieval -> confidence_gate path already handles them correctly
(zero evidence -> confidence 0.0 -> escalate; see ERROR CASE 4 in
app/test_research_retriever.py) without needing a second, cruder keyword
filter that risks false-positiving a legitimate but unusually-phrased
question.

Also stamps `started_at` — the earliest point in the graph — so memory_write
(the last node) can compute a real `latency_ms` for the audit trail.
"""

from __future__ import annotations

import re
import time

from app.schemas import GraphState

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _looks_like_pii(question: str) -> bool:
    return bool(EMAIL_PATTERN.search(question) or PHONE_PATTERN.search(question) or SSN_PATTERN.search(question))


def input_guardrail(state: GraphState) -> dict:
    print(f"[input_guardrail] checking question: {state.question!r}")
    update: dict = {"started_at": time.perf_counter()}
    if _looks_like_pii(state.question):
        print("[input_guardrail] BLOCKED: question appears to contain PII (email/phone/SSN pattern)")
        update["blocked"] = True
        update["block_reason"] = (
            "the question appears to contain personal identifying information "
            "(an email address, phone number, or SSN-like pattern)"
        )
    return update
