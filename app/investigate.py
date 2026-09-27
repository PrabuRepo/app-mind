"""
app/investigate.py — the entry point real callers (the Streamlit UI) should
use instead of calling build_graph().invoke() directly.

Checks the Redis cache (memory/cache.py) before running a fresh investigation
through the graph, so a repeated question can be answered from a previous
investigation's brief instead of paying for a brand-new one.

evals/run_eval.py deliberately does NOT go through this wrapper — it calls
build_graph().invoke() directly. The eval harness's entire job is to measure
a fresh, real run of every (question, mode) pair (and, with --trials N,
repeated fresh runs of the SAME pair — see FAILURES.md #11 on why that
variance matters). A cache hit there would report near-zero token_usage/
latency_ms and silently erase exactly the variance the harness exists to
measure. Keeping the cache entirely out of the harness's path, rather than
threading a `use_cache` flag through it, means there's no call site where
forgetting to disable it could quietly corrupt the comparative eval.

The compiled graph is cached here (functools.lru_cache), the same "build
once per process" convention as rag/search.py's client caching and
ui/app.py's old @st.cache_resource — so callers no longer need their own
graph-caching wrapper.
"""

from __future__ import annotations

import functools

from app.graph import build_graph
from app.schemas import DecisionBrief, GraphState, PipelineMode
from memory.cache import get_cached


@functools.lru_cache(maxsize=1)
def _graph():
    return build_graph()


def investigate(question: str, pipeline_mode: PipelineMode, use_cache: bool = True) -> DecisionBrief:
    """Returns the DecisionBrief for `question` under `pipeline_mode`. On a
    cache hit, no graph run happens at all — the previous investigation's
    brief is returned as-is."""
    if use_cache:
        cached = get_cached(question, pipeline_mode)
        if cached is not None:
            print(f"[investigate] cache hit: question={question!r} mode={pipeline_mode.value}")
            return cached

    result = _graph().invoke(GraphState(question=question, pipeline_mode=pipeline_mode))
    return result["decision_brief"]
