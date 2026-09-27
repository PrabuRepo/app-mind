"""
memory/memory_write.py — the last node in every run.

Persists the investigation to the Postgres audit trail (memory/db.py) and
writes it into the Redis lookup cache (memory/cache.py) so a future question
can be answered without re-running the whole pipeline (see app/investigate.py
for the read side that checks this cache before invoking the graph at all).

Both writes are best-effort: a dead Postgres or Redis must not crash an
investigation that otherwise completed successfully — same "record the
problem, don't raise" rule every other node in this pipeline follows (see
FAILURES.md #8).

Also computes the real `latency_ms` from `started_at` (stamped by
input_guardrail, the first node) — this was the one field on GraphState that
existed but nothing ever populated before this node needed a real value to
write into the audit trail.
"""

from __future__ import annotations

import time

from app.schemas import GraphState
from memory.cache import set_cached
from memory.db import write_investigation


def memory_write(state: GraphState) -> dict:
    latency_ms = (
        (time.perf_counter() - state.started_at) * 1000
        if state.started_at is not None
        else state.latency_ms
    )

    db_error = write_investigation(state, latency_ms)
    if db_error:
        print(f"[memory_write] WARNING: {db_error}")
    else:
        print(f"[memory_write] wrote audit-trail row for question={state.question!r}")

    if state.decision_brief is not None:
        set_cached(state.question, state.pipeline_mode, state.decision_brief)

    print(f"[memory_write] pipeline_mode={state.pipeline_mode.value}, latency_ms={latency_ms:.0f}")
    return {"latency_ms": latency_ms}
