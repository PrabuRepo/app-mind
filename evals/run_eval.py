"""
evals/run_eval.py — the comparative eval harness: runs every question in
evals/dataset.py through all 3 pipeline_modes, scores each result, and
writes evals/results/runs.jsonl (every run, raw) + evals/results/summary.md
(the tables the docs need).

    python -m evals.run_eval                    # everything, 1 trial per (question, mode)
    python -m evals.run_eval --only D1,D2        # just these question ids, for cheap iteration
    python -m evals.run_eval --trials 2          # override trial count
    python -m evals.run_eval --skip-error-cases  # skip re-running the 4 fault-injection cases

WHERE GROUND TRUTH COMES FROM (see evals/dataset.py + llm_as_judge/judge.py):
  - D3, B4 (Impact Analysis): checked DETERMINISTICALLY against the AST
    walk's own get_dependents() output (mcp_servers/ast_graph.py, called
    directly in-process — not the MCP server subprocess, no protocol
    overhead needed for a ground-truth check). No LLM judge call, zero cost.
  - every other question: scored by ONE llm_as_judge call per run.

ERROR-HANDLING CASES: reused, not duplicated — calls
app.test_research_retriever.run_error_handling_cases() directly, which is
exactly the function that module's own __main__ uses, so the fault-injection
logic exists in exactly one place.

COST NOTE: the judge's own token usage is tracked SEPARATELY from
`token_usage` (which reflects only the pipeline being measured, i.e. what a
real user's question would actually cost) — folding judge cost into it would
inflate every pipeline_mode's reported cost by the same fixed amount for no
reason connected to the pipeline itself.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.graph import build_graph
from app.schemas import GraphState, PipelineMode
from code_context import snapshots
from evals.dataset import DATASET, GroundTruth
from llm_as_judge.judge import RunOutcome, judge_run

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RUNS_PATH = RESULTS_DIR / "runs.jsonl"
SUMMARY_PATH = RESULTS_DIR / "summary.md"

GROUND_TRUTH_BY_ID: dict[str, GroundTruth] = {g.question_id: g for g in DATASET}


@functools.lru_cache(maxsize=1)
def _ground_truth_graph():
    """The code snapshot every impact-analysis check is measured against.

    Pin it with APPMIND_EVAL_SNAPSHOT=<commit sha> so ground truth cannot drift
    when the code repository changes; unset (or "head") uses the current head
    snapshot. The pipeline under test reads the head snapshot, so for a
    comparison to be meaningful the pinned snapshot should be the head too —
    the summary records which snapshot was used."""
    meta = snapshots.resolve_snapshot(pin=os.environ.get("APPMIND_EVAL_SNAPSHOT"))
    return meta, snapshots.load_graph(meta.id)


# ===========================================================================
# DETERMINISTIC IMPACT-ANALYSIS CHECK (no LLM)
# ===========================================================================
def _normalize(text: str) -> str:
    """Lowercase, alphanumeric only — same purpose as
    mcp_clients.ast_client._normalize, kept local since it's a one-line pure
    function used for a different check (answer-text recall, not
    question-text component matching)."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass
class ImpactCheck:
    expected: list[str]
    mentioned: list[str]
    recall: float
    unexpected_mentions: list[str]


def _expected_dependents(component: str) -> list[str]:
    result = _ground_truth_graph()[1].get_dependents(component)
    return sorted({module["module"].rsplit(".", 1)[-1] for module in result["dependent_modules"]})


def _all_component_short_names() -> set[str]:
    names: set[str] = set()
    for module in _ground_truth_graph()[1].list_components()["modules"]:
        names.add(module["module"].rsplit(".", 1)[-1])
        names.update(module["classes"].keys())
    return names


def check_impact_analysis(ground_truth: GroundTruth, answer: str) -> ImpactCheck:
    expected = _expected_dependents(ground_truth.ast_expected_component)
    normalized_answer = _normalize(answer)
    mentioned = [c for c in expected if _normalize(c) in normalized_answer]
    # "Unexpected" candidates: every other named component, excluding short
    # names that would false-positive-match too easily inside ordinary prose.
    other_components = _all_component_short_names() - set(expected) - {ground_truth.ast_expected_component}
    unexpected = [c for c in other_components if len(c) >= 6 and _normalize(c) in normalized_answer]
    recall = (len(mentioned) / len(expected)) if expected else 1.0
    return ImpactCheck(expected=expected, mentioned=mentioned, recall=recall, unexpected_mentions=unexpected)


# ===========================================================================
# ONE RUN
# ===========================================================================
@dataclass
class RunRecord:
    question_id: str
    pipeline_mode: str
    trial: int
    latency_ms: float
    token_usage: int              # the PIPELINE's own cost — never includes judge cost
    llm_calls: int
    confidence_score: float
    escalated: bool
    retrieval_errors: list[str]
    agent_errors: list[str]
    answer: str
    num_citations: int
    grounded_citation_rate: float | None   # mechanical, free — fraction of EvidenceRecord.grounded True
    judge_tokens: int = 0                  # cost of SCORING this run, tracked separately, see module docstring
    judge_false_confidence: bool | None = None
    judge_catches_planted_issue: bool | None = None
    judge_citation_accuracy: float | None = None
    judge_reasoning: str | None = None
    judge_error: str | None = None
    impact_recall: float | None = None
    impact_unexpected: list[str] = field(default_factory=list)


def run_one(ground_truth: GroundTruth, mode: PipelineMode, trial: int) -> RunRecord:
    start = time.perf_counter()
    result = build_graph().invoke(GraphState(question=ground_truth.question, pipeline_mode=mode))
    latency_ms = (time.perf_counter() - start) * 1000

    brief = result["decision_brief"]
    evidence = result["evidence"]
    grounded_rate = (sum(e.grounded for e in evidence) / len(evidence)) if evidence else None

    record = RunRecord(
        question_id=ground_truth.question_id,
        pipeline_mode=mode.value,
        trial=trial,
        latency_ms=round(latency_ms, 1),
        token_usage=result["token_usage"],
        llm_calls=result["llm_calls"],
        confidence_score=result["confidence_score"],
        escalated="escalated per policy" in brief.confidence_rationale,
        retrieval_errors=result["retrieval_errors"],
        agent_errors=result["agent_errors"],
        answer=brief.answer,
        num_citations=len(brief.citations),
        grounded_citation_rate=grounded_rate,
    )

    if ground_truth.ast_expected_component:
        if record.escalated:
            # No answer was attempted, so there's nothing to check for
            # component recall — this is a different outcome from "answered
            # confidently and named the wrong components", not the same as
            # recall=0.0. escalation_rate already reports this separately.
            record.impact_recall = None
        else:
            check = check_impact_analysis(ground_truth, brief.answer)
            record.impact_recall = check.recall
            record.impact_unexpected = check.unexpected_mentions
    else:
        outcome = RunOutcome(
            answer=brief.answer, citations=brief.citations, escalated=record.escalated,
            confidence_score=record.confidence_score, critique_flags=result["critique_flags"],
        )
        judged = judge_run(ground_truth, outcome)
        record.judge_tokens = judged.tokens
        record.judge_error = judged.error
        if judged.verdict:
            record.judge_false_confidence = judged.verdict.false_confidence
            record.judge_catches_planted_issue = judged.verdict.catches_planted_issue
            record.judge_citation_accuracy = judged.verdict.citation_accuracy
            record.judge_reasoning = judged.verdict.reasoning

    return record


# ===========================================================================
# AGGREGATION + REPORTING
# ===========================================================================
def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 3) if values else None


def aggregate_by_mode(records: list[RunRecord]) -> dict[str, dict]:
    by_mode: dict[str, list[RunRecord]] = {mode.value: [] for mode in PipelineMode}
    for record in records:
        by_mode[record.pipeline_mode].append(record)

    summary: dict[str, dict] = {}
    for mode, rows in by_mode.items():
        judged = [r for r in rows if r.judge_false_confidence is not None]
        trap_rows = [r for r in judged if GROUND_TRUTH_BY_ID[r.question_id].is_planted_trap]
        impact_rows = [r for r in rows if r.impact_recall is not None]

        summary[mode] = {
            "runs": len(rows),
            "false_confidence_rate": _mean(r.judge_false_confidence for r in judged),
            "error_catch_rate": _mean(r.judge_catches_planted_issue for r in trap_rows),
            "citation_accuracy_judge": _mean(r.judge_citation_accuracy for r in judged),
            "citation_grounded_rate_mechanical": _mean(r.grounded_citation_rate for r in rows),
            "impact_analysis_recall": _mean(r.impact_recall for r in impact_rows),
            "escalation_rate": _mean(float(r.escalated) for r in rows),
            "mean_token_usage": _mean(r.token_usage for r in rows),
            "mean_llm_calls": _mean(r.llm_calls for r in rows),
            "mean_latency_ms": _mean(r.latency_ms for r in rows),
        }
    return summary


METRIC_LABELS = [
    ("false_confidence_rate", "False-confidence rate"),
    ("error_catch_rate", "Error-catch rate (planted traps)"),
    ("citation_accuracy_judge", "Citation accuracy (LLM judge)"),
    ("citation_grounded_rate_mechanical", "Citation grounding rate (mechanical)"),
    ("impact_analysis_recall", "Impact Analysis component recall"),
    ("escalation_rate", "Escalation rate"),
    ("mean_token_usage", "Mean token usage (pipeline only, excludes judge cost)"),
    ("mean_llm_calls", "Mean LLM calls"),
    ("mean_latency_ms", "Mean latency (ms)"),
]
MODE_ORDER = [m.value for m in PipelineMode]


def _snapshot_line() -> str:
    try:
        meta, _ = _ground_truth_graph()
    except Exception as exc:   # summary must still be written if the index is unreachable
        return f"Code snapshot: unavailable ({type(exc).__name__}: {str(exc)[:120]})"
    pinned = "pinned via APPMIND_EVAL_SNAPSHOT" if os.environ.get("APPMIND_EVAL_SNAPSHOT") else "current head"
    return (f"Code snapshot: {meta.repo}@{meta.sha[:7]} (indexed "
            f"{meta.indexed_at.isoformat(timespec='seconds')}, {pinned}) — impact-analysis ground truth")


def write_summary_md(summary: dict[str, dict], error_handling_failures: list[str] | None) -> None:
    lines = [
        "# AppMind comparative eval — summary",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}Z",
        f"Dataset: {len(DATASET)} questions (see evals/dataset.py) x {len(MODE_ORDER)} pipeline_modes",
        _snapshot_line(),
        "",
        "| Metric | " + " | ".join(MODE_ORDER) + " |",
        "|---|" + "---|" * len(MODE_ORDER),
    ]
    for key, label in METRIC_LABELS:
        row = [str(summary[mode][key]) if summary[mode][key] is not None else "—" for mode in MODE_ORDER]
        lines.append(f"| {label} | " + " | ".join(row) + " |")

    lines += ["", "## Error-handling cases (reused from app/test_research_retriever.py)", ""]
    if error_handling_failures is None:
        lines.append("Skipped (--skip-error-cases).")
    elif not error_handling_failures:
        lines.append("4/4 passing — dead MCP server, hung MCP server, Qdrant unreachable, "
                     "and empty/off-topic retrieval all degrade gracefully.")
    else:
        lines.append(f"{4 - len(error_handling_failures)}/4 passing. Failed: " + "; ".join(error_handling_failures))

    lines += [
        "",
        "## Notes",
        "- Recall@K and escalation-accuracy metrics are not implemented (cut per CLAUDE.md's priority list).",
        "- The LLM judge is itself an LLM call with its own variance — its verdicts are a second "
        "opinion, not ground truth (same caution FAILURES.md #11 raised about the Critic itself).",
        "- D1 (business_functional) cannot be verified against real code: source text is only "
        "attached for incident_rca questions. \"Correct\" there means appropriately uncertain given "
        "the tools this system actually has, not omniscient. D2/B1/B6 (incident_rca) DO get "
        "real code, read from the code index (code_context/) — reflected in the numbers above.",
        "- 1 trial per (question, mode) — minimized for LLM-call cost on this capstone pass. A "
        "single run of a question won't re-surface the kind of variance FAILURES.md #11 found; "
        "add trials later (`--trials N`) if more coverage is needed.",
    ]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_runs_jsonl(records: list[RunRecord]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with RUNS_PATH.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(asdict(record)) + "\n")


# ===========================================================================
# CLI
# ===========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(description="AppMind comparative eval harness")
    parser.add_argument("--only", help="comma-separated question ids to run, e.g. D1,D2 (default: all)")
    parser.add_argument("--trials", type=int, default=1, help="repeats per (question, mode) pair")
    parser.add_argument("--skip-error-cases", action="store_true",
                        help="skip re-running the 4 fault-injection cases")
    args = parser.parse_args()

    questions = DATASET
    if args.only:
        wanted = set(args.only.split(","))
        questions = [g for g in DATASET if g.question_id in wanted]
        if not questions:
            print(f"No questions matched --only {args.only!r}. Known ids: {sorted(GROUND_TRUTH_BY_ID)}")
            return 1

    total_runs = len(questions) * len(MODE_ORDER) * args.trials
    print(f"Running {len(questions)} question(s) x {len(MODE_ORDER)} modes x {args.trials} trial(s) "
          f"= {total_runs} graph run(s)\n")

    records: list[RunRecord] = []
    for ground_truth in questions:
        for mode in PipelineMode:
            for trial in range(args.trials):
                print(f"[{ground_truth.question_id} / {mode.value} / trial {trial}] running...")
                record = run_one(ground_truth, mode, trial)
                records.append(record)
                flag = ""
                if record.judge_false_confidence:
                    flag = "  <-- FALSE CONFIDENCE"
                elif record.judge_catches_planted_issue is False:
                    flag = "  <-- MISSED PLANTED ISSUE"
                print(f"    confidence={record.confidence_score:.2f} escalated={record.escalated} "
                      f"tokens={record.token_usage} latency={record.latency_ms:.0f}ms{flag}")

    write_runs_jsonl(records)

    error_handling_failures: list[str] | None = None
    if not args.skip_error_cases:
        print("\n== re-running the 4 error-handling cases (app.test_research_retriever) ==")
        from app.test_research_retriever import run_error_handling_cases
        error_handling_failures = run_error_handling_cases()

    summary = aggregate_by_mode(records)
    write_summary_md(summary, error_handling_failures)

    print(f"\nWrote {RUNS_PATH}")
    print(f"Wrote {SUMMARY_PATH}")
    print("\n=== SUMMARY ===")
    for mode in MODE_ORDER:
        print(f"\n{mode}:")
        for key, label in METRIC_LABELS:
            print(f"  {label}: {summary[mode][key]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
