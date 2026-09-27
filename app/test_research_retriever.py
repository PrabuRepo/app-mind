"""
app/test_research_retriever.py — end-to-end check of the real Research and
Retriever logic, including the deliberate-failure cases.

    python -m app.test_research_retriever

Needs: Docker Qdrant running with ingested collections, a working
OPENAI_API_KEY (one embedding call per question), and mcp_servers/ importable.
Prints PASS/FAIL per check and exits non-zero if any fail.

The failure cases are the "error handling" evidence for the docs: each one
breaks a dependency on purpose and confirms the graph degrades gracefully —
records the problem, keeps whatever it did retrieve, and escalates rather
than crashing or bluffing. They live in their own function,
run_error_handling_cases(), so evals/run_eval.py can reuse them directly
without re-running every other check in this file (and their LLM calls) a
second time.
"""

from __future__ import annotations

import contextlib
import sys
import time

from mcp import StdioServerParameters
from qdrant_client import QdrantClient

from app.graph import build_graph
from app.retrieval import make_plan, retrieve
from app.schemas import GraphState, PipelineMode
from mcp_clients import ast_client
from rag import search as rag_search

failures: list[str] = []


def _check_against(failure_list: list[str], label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failure_list.append(label)


def check(label: str, condition: bool, detail: str = "") -> None:
    _check_against(failures, label, condition, detail)


@contextlib.contextmanager
def patched(obj, name, value):
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, original)


def run_graph(question: str, mode: PipelineMode) -> dict:
    return build_graph().invoke(GraphState(question=question, pipeline_mode=mode))


def sources(chunks) -> set[str]:
    return {c.source for c in chunks}


def run_error_handling_cases() -> list[str]:
    """The 4 deliberate-failure scenarios, standalone and independently
    callable — this is what evals/run_eval.py reuses to fold "does the
    system degrade gracefully" into its summary, without re-running the ~30
    other checks in main() below (and their LLM calls) a second time. Keeps
    the fault-injection logic in exactly one place. Returns the list of
    failed check labels (empty = all 4 cases passed)."""
    local_failures: list[str] = []

    def check_local(label: str, condition: bool, detail: str = "") -> None:
        _check_against(local_failures, label, condition, detail)

    graph_questions = {
        "rca": "Why were customers charged twice for one order?",
        "impact": "What would be affected if we changed PaymentClient's retry logic?",
    }

    print("== ERROR CASE 1: AST MCP server does not exist ==")
    dead = StdioServerParameters(command="definitely-not-a-real-command-xyz", args=[])
    with patched(ast_client, "AST_SERVER", dead):
        out = run_graph(graph_questions["impact"], PipelineMode.CRITIC_ON)
    check_local("graph did not crash and produced a brief", out["decision_brief"] is not None)
    check_local("failure recorded", any("AST MCP server unavailable" in e for e in out["retrieval_errors"]),
               str(out["retrieval_errors"]))
    check_local("Qdrant results still kept",
               any(c.collection in ("docs", "incidents") for c in out["retrieved_chunks"]))
    check_local("escalated instead of answering an impact question with no code evidence",
               "could not reach sufficient confidence" in out["decision_brief"].answer,
               f"confidence={out['confidence_score']}")
    check_local("escalation brief names the MCP failure",
               "AST MCP server unavailable" in out["decision_brief"].confidence_rationale)

    print("\n== ERROR CASE 2: AST MCP server hangs (timeout) ==")
    hung = StdioServerParameters(command=sys.executable, args=["-c", "import time; time.sleep(120)"])
    started = time.time()
    with patched(ast_client, "AST_SERVER", hung), patched(ast_client, "AST_TIMEOUT_S", 3.0):
        result = retrieve(graph_questions["impact"], make_plan("impact_analysis"))
    elapsed = time.time() - started
    check_local("gave up after the timeout instead of hanging", elapsed < 15, f"{elapsed:.1f}s")
    check_local("failure recorded", any("AST MCP server unavailable" in e for e in result.errors), str(result.errors))

    print("\n== ERROR CASE 3: Qdrant unreachable ==")
    openai_client, _ = rag_search._get_clients()
    broken = (openai_client, QdrantClient(url="http://localhost:1", timeout=2))
    with patched(rag_search, "_get_clients", lambda: broken):
        out = run_graph(graph_questions["rca"], PipelineMode.CRITIC_ON)
    check_local("graph did not crash", out["decision_brief"] is not None)
    check_local("both collection failures recorded",
               sum("search of collection" in e for e in out["retrieval_errors"]) == 2, str(out["retrieval_errors"]))
    check_local("escalated rather than answering with no evidence",
               "could not reach sufficient confidence" in out["decision_brief"].answer)
    check_local("escalation brief explains the retrieval problem",
               "Retrieval problems" in out["decision_brief"].confidence_rationale)

    print("\n== ERROR CASE 4: empty retrieval (off-topic question) ==")
    out = run_graph("What is the capital of France?", PipelineMode.CRITIC_ON)
    check_local("nothing retrieved (all below relevance threshold)", not out["retrieved_chunks"],
               str([(c.source, c.score) for c in out["retrieved_chunks"]]))
    check_local("confidence gate scored 0", out["confidence_score"] == 0.0)
    check_local("escalated to a human",
               "could not reach sufficient confidence" in out["decision_brief"].answer)

    return local_failures


def main() -> int:
    graph_questions = {
        "design": "Does OrderFlow reserve inventory before or after taking payment?",
        "rca": "Why were customers charged twice for one order?",
        "impact": "What would be affected if we changed PaymentClient's retry logic?",
    }

    print("== planning ==")
    first, retry = make_plan("incident_rca", 0), make_plan("incident_rca", 1)
    check("retry widens the search",
          all(retry.collection_top_k[c] > first.collection_top_k[c] for c in first.collection_top_k),
          f"{first.collection_top_k} -> {retry.collection_top_k}")
    check("only impact questions use the AST tools",
          make_plan("impact_analysis").use_ast_tools and not make_plan("incident_rca").use_ast_tools)
    check("unknown question type falls back to a safe plan", bool(make_plan(None).collection_top_k))

    print("\n== design-rule question (critic_on): both the doc AND the contradicting postmortem retrieved ==")
    out = run_graph(graph_questions["design"], PipelineMode.CRITIC_ON)
    src = sources(out["retrieved_chunks"])
    check("architecture_overview.md retrieved", "architecture_overview.md" in src, str(src))
    check("INC-1004 postmortem retrieved (the Critic needs it to spot the contradiction)",
          "INC-1004_oversell_report.md" in src, str(src))
    check("no retrieval errors", not out["retrieval_errors"], str(out["retrieval_errors"]))
    check("evidence citations carry real sources (not the old stub name)",
          all(e.source != "stub_source.md" for e in out["evidence"]) and bool(out["evidence"]))

    print("\n== incident/RCA question ==")
    out = run_graph(graph_questions["rca"], PipelineMode.CRITIC_ON)
    check("INC-1001 retrieved", "INC-1001_duplicate_charge.md" in sources(out["retrieved_chunks"]),
          str(sources(out["retrieved_chunks"])))

    print("\n== impact-analysis question: vector search + AST MCP tool ==")
    out = run_graph(graph_questions["impact"], PipelineMode.CRITIC_ON)
    code = [c for c in out["retrieved_chunks"] if c.collection == "code"]
    check("component 'PaymentClient' identified from the question (not the stub's OrderService guess)",
          out["target_component"] == "PaymentClient", str(out["target_component"]))
    check("AST get_dependents result retrieved", len(code) == 1 and code[0].source == "get_dependents",
          str([(c.source, c.location) for c in code]))
    check("it reports app.order_service as a dependent", bool(code) and "app.order_service" in code[0].text)
    check("docs/incidents chunks retrieved alongside",
          any(c.collection in ("docs", "incidents") for c in out["retrieved_chunks"]))

    print("\n== baseline mode now retrieves (was: no retrieval at all) ==")
    out = run_graph(graph_questions["rca"], PipelineMode.BASELINE)
    check("baseline retrieved chunks", len(out["retrieved_chunks"]) > 0)
    check("baseline skipped the evidence step", not out["evidence"])
    check("baseline still produced an answer", out["decision_brief"] is not None)

    print()
    failures.extend(run_error_handling_cases())

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
