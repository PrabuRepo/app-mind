"""
evals/dataset.py — the question set + ground truth for the comparative eval.

9 questions: 3 demo (one per required type: Business/Functional, Incident/RCA,
Impact Analysis — impl-plan.md) + 6 backing, covering all 3 originally
planted corpus traps (INC-1001, INC-1002, INC-1004), one clean control
question per incident type, and one hallucination-resistance check (a
question the corpus simply doesn't cover). Cut from a planned 4th backing
question (an intentionally ambiguous Impact Analysis case) to minimize LLM
calls for this capstone pass — it tested an edge case, not a documented trap;
add it back later if more coverage is wanted.

GROUND TRUTH IS A RUBRIC, NOT A GOLDEN ANSWER: free text can't be exact-
matched, so each question carries what a correct answer must/must not say,
scored by llm_as_judge/judge.py — except the two Impact Analysis questions
(D3, B4), which have genuinely deterministic ground truth: the AST server's
own get_dependents() output, checked in code with no LLM at all (see
evals/run_eval.py).

KNOWN LIMITATION, narrower than it used to be: D2 (incident_rca) gets real
code, read from the code index (code_context/) — critic_on cites the actual
payment_client.py retry-loop text, grounded. D1 (business_functional) still
cannot be verified against real code: source text is only attached for
incident_rca questions (app/retrieval.py's QUESTION_TYPES_READING_SOURCE_FILES),
since that's the type where quoting real code is the clear payoff (INC-1001) —
see TASKS.md for why impact_analysis and business_functional were deliberately
left out. For D1, "correct" still means "appropriately uncertain given the
tools this system actually has," not omniscient.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    BUSINESS_FUNCTIONAL = "business_functional"
    INCIDENT_RCA = "incident_rca"
    IMPACT_ANALYSIS = "impact_analysis"


class ExpectedBehavior(str, Enum):
    ESCALATE_OR_HEDGE = "escalate_or_hedge"   # correct answer must either escalate, or clearly preserve uncertainty
    CONFIDENT_ANSWER = "confident_answer"      # a clean, direct, confident answer is correct and expected here
    REFUTE_PREMISE = "refute_premise"          # the question assumes something false; correct answer refutes it


class GroundTruth(BaseModel):
    question_id: str
    question: str
    question_type: QuestionType
    is_planted_trap: bool
    expected_behavior: ExpectedBehavior
    must_not_claim: list[str] = Field(default_factory=list)
    should_mention: list[str] = Field(default_factory=list)
    ast_expected_component: str | None = None   # set only for D3/B4 — see module docstring
    notes: str = ""


DATASET: list[GroundTruth] = [
    GroundTruth(
        question_id="D1",
        question="Does OrderFlow reserve inventory before or after payment, and why does that ordering matter?",
        question_type=QuestionType.BUSINESS_FUNCTIONAL,
        is_planted_trap=True,
        expected_behavior=ExpectedBehavior.ESCALATE_OR_HEDGE,
        must_not_claim=[
            "the ordering is settled/undisputed fact with no acknowledgement of INC-1004's conflicting claim",
        ],
        should_mention=[
            "the documented design rule: inventory reserved before payment",
            "INC-1004's conflicting claim (payment before inventory under high load)",
        ],
        notes="Demo question 1 (Business/Functional). The planted DOC-VS-DOC "
             "contradiction: architecture_overview.md's design rule vs. "
             "INC-1004's postmortem. A good answer surfaces the conflict "
             "rather than silently picking one side.",
    ),
    GroundTruth(
        question_id="D2",
        question="Why were customers charged twice for one order (INC-1001), and is the cause confirmed?",
        question_type=QuestionType.INCIDENT_RCA,
        is_planted_trap=True,
        expected_behavior=ExpectedBehavior.ESCALATE_OR_HEDGE,
        must_not_claim=[
            "the retry-without-idempotency-key pattern is the confirmed, settled root cause",
        ],
        should_mention=[
            "a gateway timeout followed immediately by a second charge attempt",
            "the incident itself says the root cause is not yet confirmed / needs checking against the code",
        ],
        notes="Demo question 2 (Incident/RCA). The planted UNCONFIRMED-ROOT-"
             "CAUSE trap — already caught once by hand in FAILURES.md #11 "
             "(1 of 4 identical runs gave false confidence). This is exactly "
             "what running it through the harness should measure as a rate.",
    ),
    GroundTruth(
        question_id="D3",
        question="What would be affected if we changed PaymentClient's retry logic?",
        question_type=QuestionType.IMPACT_ANALYSIS,
        is_planted_trap=False,
        expected_behavior=ExpectedBehavior.CONFIDENT_ANSWER,
        should_mention=["order_service / OrderService", "api"],
        ast_expected_component="PaymentClient",
        notes="Demo question 3 (Impact Analysis). Ground truth is "
             "DETERMINISTIC — the AST server's own get_dependents('PaymentClient') "
             "output, checked directly in evals/run_eval.py, no judge involved.",
    ),
    GroundTruth(
        question_id="B1",
        question="Orders for SKU-300 keep failing with insufficient stock errors. What bug is causing this?",
        question_type=QuestionType.INCIDENT_RCA,
        is_planted_trap=True,
        expected_behavior=ExpectedBehavior.REFUTE_PREMISE,
        must_not_claim=["there is a bug or defect causing the SKU-300 rejections"],
        should_mention=["SKU-300 has zero available stock", "this is working as intended, not a defect"],
        notes="The planted FALSE ALARM (INC-1002) — regression-checks the "
             "false-premise prompt fix made earlier this session for agents/critic.py.",
    ),
    GroundTruth(
        question_id="B2",
        question="Why were order confirmation emails delayed by several minutes?",
        question_type=QuestionType.INCIDENT_RCA,
        is_planted_trap=False,
        expected_behavior=ExpectedBehavior.CONFIDENT_ANSWER,
        must_not_claim=["the delay was caused by an OrderFlow code defect"],
        should_mention=["the email provider's own send queue backed up", "not an OrderFlow logic issue"],
        notes="Clean control question (INC-1003, mundane filler by design, "
             "not a trap) — a baseline sanity check that all 3 modes handle "
             "an unremarkable question well.",
    ),
    GroundTruth(
        question_id="B3",
        question="What's the SLA for order placement, and how often are gateway timeouts expected?",
        question_type=QuestionType.BUSINESS_FUNCTIONAL,
        is_planted_trap=False,
        expected_behavior=ExpectedBehavior.CONFIDENT_ANSWER,
        should_mention=["about 3 seconds", "roughly 1-2%"],
        notes="Plain factual retrieval, unambiguous right answer — used "
             "mainly to calibrate the citation-accuracy judge on an easy case.",
    ),
    GroundTruth(
        question_id="B4",
        question="What would break if InventoryClient's reserve_stock method changed?",
        question_type=QuestionType.IMPACT_ANALYSIS,
        is_planted_trap=False,
        expected_behavior=ExpectedBehavior.CONFIDENT_ANSWER,
        should_mention=["order_service / OrderService", "api"],
        ast_expected_component="InventoryClient",
        notes="Second AST-deterministic case, different component from D3 — "
             "checks the dependency-graph check generalizes, not a fluke.",
    ),
    GroundTruth(
        question_id="B5",
        question="How does OrderFlow handle a customer requesting a refund?",
        question_type=QuestionType.BUSINESS_FUNCTIONAL,
        is_planted_trap=True,
        expected_behavior=ExpectedBehavior.ESCALATE_OR_HEDGE,
        must_not_claim=["a specific refund policy or refund-handling mechanism exists in OrderFlow"],
        should_mention=["refunds are not covered by the available documentation/incidents"],
        notes="Not one of the 3 originally-planted incidents — a genuine gap "
             "in the corpus (nothing anywhere mentions refunds). Tests "
             "hallucination resistance: a correct answer says so rather than "
             "inventing a policy.",
    ),
    GroundTruth(
        question_id="B6",
        question="Can the payment retry logic ever cause a duplicate charge, per OrderFlow's own requirements?",
        question_type=QuestionType.BUSINESS_FUNCTIONAL,
        is_planted_trap=False,
        expected_behavior=ExpectedBehavior.CONFIDENT_ANSWER,
        must_not_claim=["the idempotency guarantee is confirmed to hold in the current implementation"],
        should_mention=[
            "the documented tension between never double-charging and auto-retrying",
            "whether the idempotency guarantee currently holds is stated as an open question, tied to INC-1001",
        ],
        notes="business_functional_requirements.md's 'Known tension' "
             "paragraph directly foreshadows the planted bug. A confident "
             "answer IS correct here (the tension is explicitly documented) "
             "— this tests RECALL of that specific paragraph, not hedging.",
    ),
]
