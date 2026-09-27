"""
agents/test_synthesis.py — unit tests for the DETERMINISTIC logic in
agents/synthesis.py: citation-selection wiring for both the normal and
baseline paths. The LLM call is monkeypatched out (via `structured_call`),
so this suite is fast, free, and gives the same result every run.

    python -m agents.test_synthesis
"""

from __future__ import annotations

from unittest.mock import patch

from agents import synthesis
from app.llm import LLMResult
from app.schemas import EvidenceRecord, RetrievedChunk

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def _evidence(n: int) -> list[EvidenceRecord]:
    return [EvidenceRecord(claim=f"claim {i}", source=f"src{i}.md", quote=f"q{i}", grounded=True)
            for i in range(n)]


def _chunks(n: int) -> list[RetrievedChunk]:
    return [RetrievedChunk(collection="docs", source=f"src{i}.md", location="heading",
                           text=f"chunk text number {i} " * 5)
            for i in range(n)]


def test_synthesize_answer() -> None:
    print("== synthesize_answer (normal path, LLM mocked) ==")
    evidence = _evidence(3)

    reply = synthesis.SynthesizedAnswer(answer="Inventory is reserved first.", used_indices=[0, 2])
    with patch.object(synthesis, "structured_call", return_value=LLMResult(parsed=reply, tokens=42)):
        out = synthesis.synthesize_answer("q", evidence)
    check("answer passed through", out.answer == "Inventory is reserved first.")
    check("only cited indices become citations", out.citations == [evidence[0], evidence[2]],
          str(out.citations))
    check("token usage passed through", out.tokens == 42)

    print("\n== out-of-range index is dropped, valid ones kept ==")
    reply = synthesis.SynthesizedAnswer(answer="a", used_indices=[1, 99])
    with patch.object(synthesis, "structured_call", return_value=LLMResult(parsed=reply, tokens=1)):
        out = synthesis.synthesize_answer("q", evidence)
    check("only the in-range index survives", out.citations == [evidence[1]], str(out.citations))

    print("\n== empty/invalid used_indices falls back to citing everything ==")
    reply = synthesis.SynthesizedAnswer(answer="a", used_indices=[])
    with patch.object(synthesis, "structured_call", return_value=LLMResult(parsed=reply, tokens=1)):
        out = synthesis.synthesize_answer("q", evidence)
    check("falls back to all evidence rather than zero citations", out.citations == evidence)

    print("\n== LLM error surfaces with no answer ==")
    with patch.object(synthesis, "structured_call", return_value=LLMResult(error="boom")):
        out = synthesis.synthesize_answer("q", evidence)
    check("error surfaced, no answer, no citations", out.error == "boom" and out.answer is None and not out.citations)

    check("no evidence -> no LLM call, empty result", synthesis.synthesize_answer("q", []).answer is None)


def test_synthesize_baseline_answer() -> None:
    print("\n== synthesize_baseline_answer (baseline path, LLM mocked) ==")
    chunks = _chunks(2)

    reply = synthesis.SynthesizedAnswer(answer="Baseline answer.", used_indices=[1])
    with patch.object(synthesis, "structured_call", return_value=LLMResult(parsed=reply, tokens=10)):
        out = synthesis.synthesize_baseline_answer("q", chunks)
    check("answer passed through", out.answer == "Baseline answer.")
    check("exactly one citation, from the used chunk", len(out.citations) == 1)
    check("citation source/location copied from the chunk",
          out.citations[0].source == chunks[1].source and out.citations[0].location == chunks[1].location)
    check("citation is explicitly NOT marked grounded (never verified)", out.citations[0].grounded is False)
    check("citation has no quote field (no per-claim extraction happened)", out.citations[0].quote is None)
    check("claim is a raw excerpt of the chunk text, not the synthesized answer",
          out.citations[0].claim.startswith("chunk text number 1"))

    print("\n== empty/invalid used_indices falls back to citing every chunk ==")
    reply = synthesis.SynthesizedAnswer(answer="a", used_indices=[])
    with patch.object(synthesis, "structured_call", return_value=LLMResult(parsed=reply, tokens=1)):
        out = synthesis.synthesize_baseline_answer("q", chunks)
    check("falls back to citing all chunks", len(out.citations) == len(chunks))

    check("no chunks -> no LLM call, empty result", synthesis.synthesize_baseline_answer("q", []).answer is None)


def main() -> int:
    test_synthesize_answer()
    test_synthesize_baseline_answer()
    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
