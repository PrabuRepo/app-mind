"""
guardrails/input_guardrail.py — the first node in every run.

A guardrail's job is to catch bad input early and cheaply, before spending
any money on LLM calls or database queries for a question that was never
going to get a valid answer anyway.

TWO REAL CHECKS, IN ORDER:

1. PII: rejects a question that looks like it contains PII (an email
   address, phone number, or SSN-like pattern) — plain regex, no API call
   at all, deliberately deterministic and cheap. Runs FIRST, before
   anything else touches the question text, so a PII-shaped question is
   never sent anywhere (including to OpenAI for embedding, see check 2).

2. Topic relevance: rejects a question that isn't about the application at all
   (the one named by the application profile; OrderFlow today).
   Off-topic questions used to be handled only downstream (empty retrieval
   -> confidence_gate -> escalate; still true, and still the fallback if
   this check's own API call fails) — that path works, but it means the
   FULL graph runs (supervisor, research, retriever, evidence, critic,
   confidence_gate) just to reach the same "no" a much cheaper check could
   give immediately. This embeds the question once (the same
   text-embedding-3-small call retrieval would make anyway) and compares it
   against a fixed reference embedding of what the application's scope actually
   is, via cosine similarity. The reference text is `scope.description` in the
   application profile (config/apps/<id>.yaml); a profile without one skips this
   check entirely, and the downstream empty-retrieval path still applies.

   THRESHOLD IS MEASURED, NOT GUESSED — same discipline as rag/search.py's
   own MIN_SCORE. Tested OrderFlow's reference description against all
   9 real eval-dataset questions (on-topic) and 7 genuinely off-topic ones:
   on-topic scored 0.28-0.61, off-topic scored -0.03-0.10 — a clean gap.
   0.18 sits in the middle of that gap with margin on both sides.

   FAILS OPEN: if the embedding call itself errors (network, quota, OpenAI
   down), this check is skipped and the question proceeds normally rather
   than being blocked by a guardrail that couldn't actually check anything
   — the downstream empty-retrieval path still catches a genuinely
   off-topic question either way.

Also stamps `started_at` — the earliest point in the graph — so memory_write
(the last node) can compute a real `latency_ms` for the audit trail.
"""

from __future__ import annotations

import functools
import re
import time

from app.schemas import GraphState
from app_profile.registry import select_profile
from rag.search import embed_query

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# See "Topic relevance" above for how the description and threshold were chosen.
# The threshold is a platform constant, not per-application config.
MIN_TOPIC_SCORE = 0.18


def _looks_like_pii(question: str) -> bool:
    return bool(EMAIL_PATTERN.search(question) or PHONE_PATTERN.search(question) or SSN_PATTERN.search(question))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    return dot / (norm_a * norm_b)


@functools.lru_cache(maxsize=1)
def _topic() -> tuple[str, str | None]:
    """(application name, scope description or None) from the application
    profile. Cached: the profile is read once per process. A broken profile
    raises here on purpose: a misconfiguration should be loud, not fail open."""
    profile = select_profile()
    return profile.app.name, profile.scope.description


@functools.lru_cache(maxsize=1)
def _topic_reference_vector() -> tuple[float, ...]:
    # Cached: this exact text only ever needs to be embedded once per process,
    # not once per question. Returned as a tuple so it's hashable for lru_cache.
    description = _topic()[1]
    return tuple(embed_query(description, caller="input_guardrail_topic_reference"))


def _topic_relevance_score(question: str) -> float | None:
    """None means the check couldn't run (embedding call failed) — the
    caller treats that as fail-open, not as a block."""
    try:
        question_vector = embed_query(question, caller="input_guardrail_topic_check")
        return _cosine(question_vector, list(_topic_reference_vector()))
    except Exception as exc:
        print(f"[input_guardrail] WARNING: topic relevance check failed, skipping it: "
              f"{type(exc).__name__}: {str(exc)[:200]}")
        return None


def input_guardrail(state: GraphState) -> dict:
    print(f"[input_guardrail] checking question: {state.question!r}")
    update: dict = {"started_at": time.perf_counter(), "trace": state.trace + ["input_guardrail"]}

    if _looks_like_pii(state.question):
        print("[input_guardrail] BLOCKED: question appears to contain PII (email/phone/SSN pattern)")
        update["blocked"] = True
        update["block_reason"] = (
            "the question appears to contain personal identifying information "
            "(an email address, phone number, or SSN-like pattern)"
        )
        return update

    app_name, description = _topic()
    if description is None:
        print("[input_guardrail] profile has no scope.description: topic relevance check skipped")
        return update

    score = _topic_relevance_score(state.question)
    if score is not None:
        update["trace"] = update["trace"] + ["llm:embedding"]
        print(f"[input_guardrail] topic relevance score={score:.4f} (threshold={MIN_TOPIC_SCORE})")
        if score < MIN_TOPIC_SCORE:
            print(f"[input_guardrail] BLOCKED: question does not appear to be about {app_name}")
            update["blocked"] = True
            update["block_reason"] = (
                f"the question does not appear to relate to {app_name} "
                f"(topic relevance score {score:.2f}, below the {MIN_TOPIC_SCORE} threshold)"
            )

    return update
