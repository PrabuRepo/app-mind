"""
agents/test_evidence.py — unit tests for the DETERMINISTIC logic in
agents/evidence.py: the grounding check and the extraction wiring. The LLM
call is monkeypatched out (via `structured_call`), so this suite is fast,
free, and gives the same result every run.

    python -m agents.test_evidence
"""

from __future__ import annotations

from unittest.mock import patch

from agents import evidence
from app.llm import LLMResult
from app.schemas import RetrievedChunk

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


CHUNK_TEXT = (
    "## Design rule\nInventory is always reserved **before** payment is attempted "
    "— the system is explicitly designed to avoid charging a customer for stock "
    "we don't have."
)


def _chunk(source="architecture_overview.md", text=CHUNK_TEXT) -> RetrievedChunk:
    return RetrievedChunk(collection="docs", source=source, location="Design rule", text=text)


def test_is_grounded() -> None:
    print("== is_grounded ==")
    check("exact quote (ignoring markdown/case/whitespace)",
          evidence.is_grounded("inventory is always reserved before payment is attempted", CHUNK_TEXT))
    check("near-verbatim, one word off, still grounded",
          evidence.is_grounded("Inventory is always reserved before payment is attemptedd", CHUNK_TEXT))
    check("fabricated quote is NOT grounded",
          not evidence.is_grounded("Payment is always captured before inventory is reserved", CHUNK_TEXT))
    check("quote from a different source's wording is NOT grounded",
          not evidence.is_grounded("orders are processed within three seconds under normal load", CHUNK_TEXT))
    check("too-short quote is NOT grounded (would match almost anything)",
          not evidence.is_grounded("payment is", CHUNK_TEXT))


def test_extract_evidence_wiring() -> None:
    print("\n== extract_evidence (LLM mocked) ==")
    parsed = evidence.EvidenceExtraction(claims=[
        evidence.ExtractedClaim(chunk_id=0, claim="Inventory is reserved before payment.",
                                quote="Inventory is always reserved before payment is attempted"),
        evidence.ExtractedClaim(chunk_id=0, claim="A fabricated claim.", quote="something not in the chunk at all"),
        evidence.ExtractedClaim(chunk_id=7, claim="Out-of-range chunk id.", quote="doesn't matter"),
    ])
    with patch.object(evidence, "structured_call", return_value=LLMResult(parsed=parsed, tokens=123)):
        out = evidence.extract_evidence("Is inventory reserved before payment?", [_chunk()])

    check("out-of-range chunk_id is dropped", len(out.items) == 2, str(len(out.items)))
    check("source/location copied from the chunk, not invented",
          out.items[0].source == "architecture_overview.md" and out.items[0].location == "Design rule")
    check("real quote marked grounded", out.items[0].grounded)
    check("fabricated quote marked NOT grounded", not out.items[1].grounded)
    check("token usage passed through", out.tokens == 123)

    with patch.object(evidence, "structured_call", return_value=LLMResult(error="boom")):
        out = evidence.extract_evidence("q", [_chunk()])
    check("LLM error surfaces with no evidence", out.error == "boom" and not out.items)

    check("no chunks -> no LLM call, empty result", evidence.extract_evidence("q", []).items == [])


def main() -> int:
    test_is_grounded()
    test_extract_evidence_wiring()
    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
