"""
memory/db.py — Postgres audit trail: one row per completed investigation.

Client setup mirrors rag/search.py's _get_clients() / app/llm.py's _openai():
read connection details from .env via python-dotenv, build once, reuse.
Postgres runs locally (docker-compose.yml), so a fresh short-lived connection
per call is fine — this writes once per investigation, not in a hot loop, so
a real pool (psycopg_pool, not in requirements.txt) isn't worth the
complexity.

Like every other node in the pipeline (see FAILURES.md #8), write_investigation()
never raises: a dead Postgres must not crash an investigation that otherwise
completed successfully. It returns an error string instead, same convention
as app/llm.py's LLMResult.error.
"""

from __future__ import annotations

import functools
import json
import os
import uuid

import psycopg
from dotenv import load_dotenv

from app.schemas import GraphState

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS investigations (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    question TEXT NOT NULL,
    pipeline_mode TEXT NOT NULL,
    question_type TEXT,
    target_component TEXT,
    confidence_score DOUBLE PRECISION NOT NULL,
    escalated BOOLEAN NOT NULL,
    answer TEXT NOT NULL,
    citations JSONB NOT NULL,
    critique_flags JSONB NOT NULL,
    retrieval_errors JSONB NOT NULL,
    agent_errors JSONB NOT NULL,
    retry_count INTEGER NOT NULL,
    token_usage INTEGER NOT NULL,
    llm_calls INTEGER NOT NULL,
    latency_ms DOUBLE PRECISION
);
"""

INSERT_SQL = """
INSERT INTO investigations (
    id, question, pipeline_mode, question_type, target_component,
    confidence_score, escalated, answer, citations, critique_flags,
    retrieval_errors, agent_errors, retry_count, token_usage, llm_calls, latency_ms
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
"""

_schema_ready = False


@functools.lru_cache(maxsize=1)
def _connection_string() -> str:
    load_dotenv()
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB", "appmind")
    user = os.environ.get("POSTGRES_USER", "appmind")
    password = os.environ.get("POSTGRES_PASSWORD", "appmind")
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


def _connect() -> psycopg.Connection:
    return psycopg.connect(_connection_string(), connect_timeout=5)


def ensure_schema() -> None:
    """Idempotent — CREATE TABLE IF NOT EXISTS, run at most once per process."""
    global _schema_ready
    if _schema_ready:
        return
    with _connect() as conn:
        conn.execute(CREATE_TABLE_SQL)
    _schema_ready = True


def _is_escalated(confidence_rationale: str) -> bool:
    # Same signal ui/streamlit_app.py and evals/run_eval.py already use:
    # escalate()'s confidence_rationale always contains this exact phrase.
    return "escalated per policy" in confidence_rationale


def write_investigation(state: GraphState, latency_ms: float) -> str | None:
    """Writes one audit-trail row for a completed investigation. `latency_ms`
    is passed explicitly rather than read from state.latency_ms, since
    memory_write computes it just before this call and hasn't merged it into
    state yet (LangGraph merges a node's returned dict AFTER the node runs).
    Returns None on success, an error string on failure — never raises."""
    brief = state.decision_brief
    if brief is None:
        return "no decision_brief on state (should not happen post-synthesis/escalate)"
    try:
        ensure_schema()
        with _connect() as conn:
            conn.execute(
                INSERT_SQL,
                (
                    str(uuid.uuid4()),
                    state.question,
                    state.pipeline_mode.value,
                    state.question_type,
                    state.target_component,
                    state.confidence_score,
                    _is_escalated(brief.confidence_rationale),
                    brief.answer,
                    json.dumps([c.model_dump() for c in brief.citations]),
                    json.dumps([f.model_dump() for f in state.critique_flags]),
                    json.dumps(state.retrieval_errors),
                    json.dumps(state.agent_errors),
                    state.retry_count,
                    state.token_usage,
                    state.llm_calls,
                    latency_ms,
                ),
            )
    except Exception as exc:  # connection refused, auth failure, bad schema...
        return f"Postgres write failed: {type(exc).__name__}: {str(exc)[:200]}"
    return None
