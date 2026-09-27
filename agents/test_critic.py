"""
agents/test_critic.py — unit tests for the DETERMINISTIC logic in
agents/critic.py: the mechanical uncited-flag derivation and the sticky-flag
carry-over rules. The LLM call is monkeypatched out (via `structured_call`),
so this suite is fast, free, and gives the same result every run — unlike a
live call, whose judgment quality varies by design (see FAILURES.md #11) and
belongs in the eval harness, not here.

    python -m agents.test_critic
"""

from __future__ import annotations

from unittest.mock import patch

from agents import critic
from app.llm import LLMResult
from app.schemas import CritiqueFlag, CritiqueFlagType, EvidenceRecord

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def test_uncited_flags_are_mechanical() -> None:
    print("== _uncited_flags (derived from grounding, not the LLM) ==")
    evidence_records = [
        EvidenceRecord(claim="a", source="x.md", grounded=True),
        EvidenceRecord(claim="b", source="y.md", grounded=False),
        EvidenceRecord(claim="c", source="z.md", grounded=False),
    ]
    flags = critic._uncited_flags(evidence_records)
    check("one uncited flag per ungrounded record", len(flags) == 2, str(len(flags)))
    check("all flagged as UNCITED", all(f.flag_type == CritiqueFlagType.UNCITED for f in flags))


def test_critic_sticky_flags() -> None:
    print("\n== review_evidence (LLM mocked): sticky flags ==")
    grounded_evidence = [EvidenceRecord(claim="a", source="x.md", quote="a", grounded=True)]

    old_gap = CritiqueFlag(flag_type=CritiqueFlagType.GAP, description="root cause not confirmed", resolved=False)
    old_contradiction = CritiqueFlag(flag_type=CritiqueFlagType.CONTRADICTION, description="A vs B", resolved=False)
    already_settled = CritiqueFlag(flag_type=CritiqueFlagType.GAP, description="old, already resolved",
                                   resolved=True, resolution="fixed last time")
    stale_uncited = CritiqueFlag(flag_type=CritiqueFlagType.UNCITED, description="stale, must not carry over",
                                 resolved=False)

    # Model resolves flag 0 (old_gap) with a reason, stays silent on flag 1 (old_contradiction),
    # and raises one new gap.
    reply = critic.CriticReview(
        previous_flag_verdicts=[critic.FlagVerdict(flag_number=0, resolved=True, reason="now confirmed by X")],
        new_flags=[critic.RaisedFlag(flag_type=CritiqueFlagType.GAP, description="a fresh problem")],
    )
    with patch.object(critic, "structured_call", return_value=LLMResult(parsed=reply, tokens=50)):
        out = critic.review_evidence("q", grounded_evidence,
                                     [old_gap, old_contradiction, already_settled, stale_uncited])

    by_type = {(f.flag_type, f.description): f for f in out.items}
    check("model-resolved flag is marked resolved, with its reason kept",
          by_type[(CritiqueFlagType.GAP, "root cause not confirmed")].resolved
          and by_type[(CritiqueFlagType.GAP, "root cause not confirmed")].resolution == "now confirmed by X")
    check("flag with NO verdict defaults to still unresolved (not silently dropped)",
          not by_type[(CritiqueFlagType.CONTRADICTION, "A vs B")].resolved)
    check("already-settled flag stays settled and is not re-sent to the model",
          by_type[(CritiqueFlagType.GAP, "old, already resolved")].resolved)
    check("new flag from this pass is present", (CritiqueFlagType.GAP, "a fresh problem") in by_type)
    check("stale UNCITED flag from a previous pass is dropped (recomputed fresh below)",
          not any(d == "stale, must not carry over" for (_, d) in by_type))
    check("UNCITED flags come from the grounding check, not the model",
          sum(f.flag_type == CritiqueFlagType.UNCITED for f in out.items) == 0)  # this evidence is all grounded

    print("\n== review_evidence: LLM failure keeps every flag exactly as it was ==")
    with patch.object(critic, "structured_call", return_value=LLMResult(error="down")):
        out = critic.review_evidence("q", grounded_evidence, [old_gap, already_settled])
    check("unresolved flag survives an LLM outage unresolved (never silently cleared)",
          any(f.description == "root cause not confirmed" and not f.resolved for f in out.items))
    check("error is surfaced", out.error == "down")

    check("no evidence -> no LLM call, empty result", critic.review_evidence("q", []).items == [])


def main() -> int:
    test_uncited_flags_are_mechanical()
    test_critic_sticky_flags()
    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
