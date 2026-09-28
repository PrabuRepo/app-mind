"""
rag/search.py — the RAG (vector search) half of retrieval: embedding queries
and searching the `docs`/`incidents` Qdrant collections.

This module only knows about vectors and Qdrant. It does not know about
questions failing gracefully, code-dependency lookups, or LangGraph — that
coordination lives in app/retrieval.py, which calls the functions here and
merges their results with mcp_clients.ast_client's. Keeping this module free
of try/except also means a real failure (Qdrant down, a bad API key) surfaces
as a normal exception here, which is exactly what the coordinator needs to
catch and record.
"""

from __future__ import annotations

import functools

from app.schemas import RetrievedChunk
from ingest.run_ingestion import EMBEDDING_MODEL, load_env_and_clients

# Chunks scoring below this cosine similarity are dropped as irrelevant, so an
# off-topic question yields an EMPTY retrieval (which the confidence gate
# escalates) rather than the "least bad" chunks dressed up as evidence.
# Chosen from measured scores (text-embedding-3-small, this corpus):
# off-topic questions peak at ~0.17, a vague on-topic one at ~0.31, real
# questions >= 0.57.
MIN_SCORE = 0.25

# Base chunks-per-collection by question type; each retry adds RETRY_EXTRA_TOP_K
# so a Critic-triggered second look casts a wider net than the first.
BASE_TOP_K: dict[str, dict[str, int]] = {
    "business_functional": {"docs": 4, "incidents": 3},
    "incident_rca":        {"docs": 3, "incidents": 5},
    "impact_analysis":     {"docs": 3, "incidents": 2},
}
RETRY_EXTRA_TOP_K = 3


@functools.lru_cache(maxsize=1)
def _get_clients():
    # One OpenAI + Qdrant client per process, reused across graph runs.
    return load_env_and_clients()


def embed_query(text: str, caller: str = "retrieval") -> list[float]:
    """Embed a single query string with the same model used at ingestion time.

    This IS a real OpenAI API call (just an embedding, not a chat completion)
    — it fires for every question that reaches retrieval, even one that ends
    up with zero relevant chunks. Logged separately from `[llm]` in
    app/llm.py so the two costs aren't confused with each other. `caller`
    labels WHICH embedding call this is (e.g. "retrieval" vs.
    "input_guardrail_topic_check") — two different call sites embed the same
    question text for two different reasons; see guardrails/input_guardrail.py.
    """
    openai_client, _ = _get_clients()
    print(f"[llm] embedding ({caller}): calling {EMBEDDING_MODEL}")
    return openai_client.embeddings.create(model=EMBEDDING_MODEL, input=[text]).data[0].embedding


def vector_search(collection: str, query_vector: list[float], top_k: int) -> list[RetrievedChunk]:
    """Top-`top_k` chunks in `collection` nearest to `query_vector`, below
    MIN_SCORE dropped. Raises on a connection/API failure — the caller
    (app/retrieval.py) is responsible for catching that and degrading."""
    _, qdrant_client = _get_clients()
    points = qdrant_client.query_points(
        collection_name=collection, query=query_vector, limit=top_k, score_threshold=MIN_SCORE,
    ).points
    return [
        RetrievedChunk(
            collection=collection,
            source=point.payload["source"],
            location=point.payload["heading"],
            text=point.payload["text"],
            score=round(point.score, 4),
        )
        for point in points
    ]


def plan_top_k(question_type: str, retry_count: int) -> dict[str, int]:
    """How many chunks to pull from each collection for this question type,
    widened on each retry. `question_type` must be a key of BASE_TOP_K —
    resolving an unknown type to a fallback is the caller's job (it is a
    research-policy decision, not a RAG one)."""
    return {collection: base + RETRY_EXTRA_TOP_K * retry_count
            for collection, base in BASE_TOP_K[question_type].items()}
