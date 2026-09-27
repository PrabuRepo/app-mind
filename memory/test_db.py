"""
memory/test_db.py — tests memory/db.py against the REAL local Postgres
container (per CLAUDE.md: real connections now, not mocks/in-memory
stand-ins — that hedge was only for before Docker was confirmed working).

Round-trips a row, then confirms a broken connection degrades to an error
string instead of raising — memory_write must never crash the graph over a
dead Postgres.

    python -m memory.test_db
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import psycopg

from app.schemas import DecisionBrief, EvidenceRecord, GraphState, PipelineMode
from memory import db

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def _sample_state() -> tuple[GraphState, str]:
    question = f"test question {uuid.uuid4()}"
    state = GraphState(
        question=question,
        pipeline_mode=PipelineMode.CRITIC_ON,
        question_type="business_functional",
        confidence_score=0.9,
        retry_count=0,
        token_usage=123,
        llm_calls=2,
        decision_brief=DecisionBrief(
            answer="test answer",
            citations=[EvidenceRecord(claim="c", source="s.md")],
            confidence_rationale="confidence_score=0.90, no blocking flags",
        ),
    )
    return state, question


def test_write_and_read_back() -> None:
    print("== write_investigation round-trip ==")
    state, question = _sample_state()
    error = db.write_investigation(state, latency_ms=42.5)
    check("write_investigation returns no error", error is None, str(error))

    with psycopg.connect(db._connection_string()) as conn:
        row = conn.execute(
            "SELECT question, pipeline_mode, confidence_score, escalated, latency_ms "
            "FROM investigations WHERE question = %s",
            (question,),
        ).fetchone()
    check("row exists", row is not None)
    if row:
        check("question matches", row[0] == question)
        check("pipeline_mode matches", row[1] == "critic_on")
        check("escalated is False for a synthesized (non-escalated) answer", row[3] is False)
        check("latency_ms stored", row[4] == 42.5, str(row[4]))


def test_missing_brief_returns_error() -> None:
    print("== write_investigation with no decision_brief ==")
    state = GraphState(question="no brief yet", pipeline_mode=PipelineMode.BASELINE)
    error = db.write_investigation(state, latency_ms=1.0)
    check("returns an error string rather than raising or silently succeeding", isinstance(error, str) and bool(error))


def test_degrades_on_bad_connection() -> None:
    print("== write_investigation degrades gracefully when Postgres is unreachable ==")
    state, _ = _sample_state()
    with patch.object(db, "_connection_string", return_value="host=localhost port=1 dbname=x user=x password=x"):
        error = db.write_investigation(state, latency_ms=1.0)
    check("returns an error string instead of raising", isinstance(error, str) and bool(error))


if __name__ == "__main__":
    test_write_and_read_back()
    test_missing_brief_returns_error()
    test_degrades_on_bad_connection()
    print(f"\n{len(failures)} failure(s)" if failures else "\nAll checks passed.")
    raise SystemExit(1 if failures else 0)
