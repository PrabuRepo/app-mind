"""
app/retrieval.py — the "go and look things up" coordinator behind the
Research and Retriever nodes in graph.py.

This module decides WHAT to fetch and merges the results; it does not know
HOW any single fetch works — that lives in the two packages it calls:
  rag.search          — embedding a query and searching Qdrant's `docs`/`incidents`
  mcp_clients.ast_client — calling the custom AST dependency MCP server

Two jobs:
  1. make_plan()  — decide where to look (pure logic, no I/O, no LLM).
  2. retrieve()   — execute the plan and merge both sources' results.
     Never crashes: each external call (OpenAI, Qdrant, the MCP subprocess)
     is wrapped here, and a failure is recorded as a human-readable string in
     RetrievalResult.errors while retrieval carries on with what it got. The
     graph then degrades to an honest escalation instead of a stack trace —
     this is the error-handling behaviour the eval checks.

WHY BOTH COLLECTIONS ARE SEARCHED FOR EVERY QUESTION TYPE:
docs and incidents are kept as separate collections (so each can have its own
top_k), but a question about the design ("is inventory reserved before
payment?") must also see the incident postmortems, or the Critic can never
notice that INC-1004 contradicts the architecture doc. The corpus is small
enough that the extra search costs almost nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import ResearchPlan, RetrievedChunk
from mcp_clients.ast_client import lookup_dependents
from mcp_clients.github_client import fetch_source_files
from rag.search import BASE_TOP_K, embed_query, plan_top_k, vector_search

# Falls back to this question type when the supervisor's classification is
# missing or unrecognized (see rag.search.BASE_TOP_K for the valid set).
DEFAULT_QUESTION_TYPE = "business_functional"

# Impact-analysis questions need the code-dependency graph (blast radius).
# Incident RCA questions ALSO get AST tools now (not just impact analysis):
# resolving which component the question names is exactly the file-path
# resolution the GitHub step needs, and the resulting dependency facts are
# legitimate RCA context too (e.g. what else calls PaymentClient.charge),
# not just impact-analysis noise. See TASKS.md's 2026-09-27 GitHub MCP entry.
QUESTION_TYPES_USING_AST_TOOLS = {"impact_analysis", "incident_rca"}

# Real source text (via the GitHub MCP server) is only fetched for incident
# RCA questions — that's the case where quoting the actual bug matters
# (INC-1001). Impact Analysis already has a free, deterministic ground-truth
# check built on AST facts alone; adding a live GitHub call there would add
# cost/latency/a new failure mode without a clear benefit to that metric.
QUESTION_TYPES_USING_GITHUB_TOOLS = {"incident_rca"}


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    target_component: str | None = None
    mcp_calls: list[str] = field(default_factory=list)
    # Which MCP tools were actually invoked this call — appended when the
    # call is attempted, regardless of whether it then succeeds or fails
    # (an attempt that errors out is still an invocation). Lets the retriever
    # node in graph.py report real MCP usage in the trace, not just what the
    # research plan intended.


def _describe_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def make_plan(question_type: str | None, retry_count: int = 0) -> ResearchPlan:
    """Pick sources and chunk counts. Deterministic on purpose: planning
    where to look doesn't need an LLM call, and a deterministic plan keeps
    the three pipeline modes comparable in the eval."""
    resolved_type = question_type if question_type in BASE_TOP_K else DEFAULT_QUESTION_TYPE
    top_k = plan_top_k(resolved_type, retry_count)
    use_ast_tools = resolved_type in QUESTION_TYPES_USING_AST_TOOLS
    use_github_tools = resolved_type in QUESTION_TYPES_USING_GITHUB_TOOLS
    attempt = f"retry {retry_count}, widened top_k" if retry_count else "first pass"
    return ResearchPlan(
        collection_top_k=top_k,
        use_ast_tools=use_ast_tools,
        use_github_tools=use_github_tools,
        rationale=(f"{resolved_type} ({attempt}): search {top_k}"
                  + (" + AST dependency tools" if use_ast_tools else "")
                  + (" + GitHub source read" if use_github_tools else "")),
    )


def _search_vector_collections(question: str, plan: ResearchPlan, result: RetrievalResult) -> None:
    try:
        query_vector = embed_query(question)
    except Exception as exc:  # network, auth, quota... never let it escape
        result.errors.append(f"embedding failed, skipped vector search: {_describe_error(exc)}")
        return
    for collection, top_k in plan.collection_top_k.items():
        try:
            result.chunks.extend(vector_search(collection, query_vector, top_k))
        except Exception as exc:
            result.errors.append(f"search of collection {collection!r} failed: {_describe_error(exc)}")


def _search_code_dependencies(question: str, target_component: str | None, result: RetrievalResult) -> list[str]:
    """Returns the file paths AST resolved the question's component(s) to, so
    the caller can optionally chain a real GitHub source read onto them —
    empty on any failure (nothing to chain)."""
    result.mcp_calls.append("AST MCP")
    try:
        ast_result = lookup_dependents(question, target_component)
    except Exception as exc:  # includes TimeoutError and a server that won't start
        result.errors.append(f"AST MCP server unavailable: {_describe_error(exc)}")
        return []
    result.chunks.extend(ast_result.chunks)
    result.errors.extend(ast_result.errors)
    result.target_component = ast_result.target_component
    return ast_result.file_paths


def _search_source_code(file_paths: list[str], result: RetrievalResult) -> None:
    result.mcp_calls.append("GitHub MCP")
    try:
        github_result = fetch_source_files(file_paths)
    except Exception as exc:  # includes TimeoutError, a bad/missing token, network failure
        result.errors.append(f"GitHub MCP server unavailable: {_describe_error(exc)}")
        return
    result.chunks.extend(github_result.chunks)
    result.errors.extend(github_result.errors)


def retrieve(question: str, plan: ResearchPlan, target_component: str | None = None) -> RetrievalResult:
    result = RetrievalResult(target_component=target_component)
    _search_vector_collections(question, plan, result)
    if plan.use_ast_tools:
        file_paths = _search_code_dependencies(question, target_component, result)
        if plan.use_github_tools and file_paths:
            _search_source_code(file_paths, result)
    return result
