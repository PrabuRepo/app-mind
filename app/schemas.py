"""
schemas.py — the shared "contract" for AppMind's agent graph.

WHY THIS FILE EXISTS FIRST (before any agent logic):
Every agent in the LangGraph pipeline reads from and writes to one shared
state object. If that state object isn't precisely defined up front, agents
end up disagreeing about what fields exist, what type they are, or what a
"citation" even looks like. Pydantic solves this by giving us:
  1. A single source of truth for what data looks like at every step.
  2. Automatic validation — if an agent tries to put a string where a list
     was expected, Pydantic raises an error immediately instead of letting
     a malformed object silently flow deeper into the pipeline.
  3. Easy conversion to/from JSON, which matters because LLM APIs return
     text, and we frequently ask the model to return JSON that matches one
     of these schemas exactly (a technique often called "structured output").

If you're new to Pydantic: think of each `class Foo(BaseModel):` block below
as a strict form. Every field you list is a blank on the form. Some blanks
are required, some have a default value pre-filled (via `= ...` or
`Field(default=...)`), and Pydantic refuses to accept a filled-out form that
doesn't match the shape you defined.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# PipelineMode
# ---------------------------------------------------------------------------
# This is the single flag that makes your mandatory comparative eval possible.
# Instead of building three separate systems (one plain-RAG baseline, one
# without a Critic, one with a Critic), we build ONE LangGraph graph and use
# this flag to decide, at run time, which nodes actually execute.
#
# An Enum (rather than a plain string) is used here so that:
#   - Only these three exact values are ever valid — a typo like
#     "critic_ff" is caught immediately by Pydantic, not discovered later
#     when your eval results look wrong.
#   - Your code can compare `mode == PipelineMode.CRITIC_ON` instead of
#     comparing raw strings, which is both safer and easier to read.
class PipelineMode(str, Enum):
    BASELINE = "baseline"       # Retrieve -> answer directly. No Evidence/Critic/Gate.
    CRITIC_OFF = "critic_off"   # Full path, but the Critic node is skipped.
    CRITIC_ON = "critic_on"     # Full path, including the Critic. This is "AppMind" proper.


# ---------------------------------------------------------------------------
# EvidenceRecord
# ---------------------------------------------------------------------------
# Produced by the Evidence Agent. Each instance represents ONE claim the
# system is making, plus where that claim came from. This is what makes the
# final answer "auditable" — every sentence in the decision brief should be
# traceable back to one of these records.
class EvidenceRecord(BaseModel):
    claim: str
    # The specific factual statement being made, in plain English.
    # Example: "Inventory is reserved before payment is captured."

    source: str
    # Which document or tool produced this claim.
    # For RAG-sourced claims: the filename, e.g. "architecture_overview.md".
    # For MCP/AST-sourced claims: the tool name, e.g. "get_dependents".

    location: Optional[str] = None
    # A more precise pointer within the source, if available.
    # Example: a section heading in a doc, or a function name in code.
    # Optional because not every source has a meaningful sub-location.

    quote: Optional[str] = None
    # The verbatim excerpt from the source that supports the claim. Kept on
    # the record so the Critic (and a human reading the brief) can see the
    # actual words, and so `grounded` can be checked mechanically rather than
    # taken on trust from the model.

    grounded: bool = True
    # True if the quote really appears in the cited source (checked in code,
    # not self-reported by the LLM). False means the claim couldn't be tied to
    # the source's actual text — exactly the kind of thing the Critic looks for.


# ---------------------------------------------------------------------------
# CritiqueFlag
# ---------------------------------------------------------------------------
# Produced by the Critic Agent. Each flag represents ONE problem found while
# reviewing the Evidence Agent's output. The Critic doesn't rewrite the
# answer itself — it raises flags, and the graph's routing logic decides
# what happens next (retry research, or let it through).
class CritiqueFlagType(str, Enum):
    CONTRADICTION = "contradiction"  # Two pieces of evidence disagree with each other.
    UNCITED = "uncited"              # A claim exists with no supporting EvidenceRecord.
    GAP = "gap"                      # The question isn't fully answered by the evidence gathered.


class CritiqueFlag(BaseModel):
    flag_type: CritiqueFlagType
    description: str
    # Plain-English explanation of the problem, e.g. "INC-1004 claims payment
    # happens before inventory reservation, which contradicts
    # architecture_overview.md's stated design rule."

    resolved: bool = False
    # Starts False. Gets set to True if a retry round successfully addresses
    # this specific flag. The Confidence Gate checks whether any flags are
    # still unresolved before allowing synthesis to proceed.

    resolution: Optional[str] = None
    # Why the Critic considers the flag resolved — kept for the audit trail so
    # a flag never just silently disappears between retry passes.


# ---------------------------------------------------------------------------
# DecisionBrief
# ---------------------------------------------------------------------------
# Produced by the Synthesis Agent — this is the final, user-facing output.
# Everything upstream exists to produce a trustworthy version of this object.
class DecisionBrief(BaseModel):
    answer: str
    # The actual answer to the user's question, in plain English.

    citations: list[EvidenceRecord] = Field(default_factory=list)
    # The subset of evidence actually used to construct the answer above.
    # `default_factory=list` (rather than `= []`) avoids a classic Python
    # bug where a single mutable default list would be shared across every
    # instance of this class. Pydantic handles this correctly either way,
    # but writing it this way is the standard, safe convention.

    confidence_rationale: str
    # A short explanation of WHY the system is or isn't confident — not just
    # a number, but the reasoning, since that's what makes this auditable
    # rather than a black-box score.

    affected_components: Optional[list[str]] = None
    # Only populated for Impact Analysis questions — e.g. ["OrderService",
    # "PaymentClient"]. None for question types where this doesn't apply.


# ---------------------------------------------------------------------------
# RetrievedChunk + ResearchPlan
# ---------------------------------------------------------------------------
# What the Research and Retriever nodes pass along. A chunk keeps its origin
# (source + location) instead of being a bare string, because the Evidence
# Agent needs that origin to build a citation — a string alone can't tell you
# which document, or which tool, it came from.
class RetrievedChunk(BaseModel):
    collection: str
    # Where it came from: "docs" or "incidents" (Qdrant), or "code" (MCP/AST tool output).

    source: str
    # Filename for RAG chunks ("architecture_overview.md"); tool name for
    # code results ("get_dependents"). Same convention as EvidenceRecord.source.

    location: Optional[str] = None
    # Section heading for RAG chunks; the resolved component for code results.

    text: str
    # The chunk text, or the tool's raw JSON output for code results.

    score: Optional[float] = None
    # Cosine similarity for RAG chunks (higher = closer). None for tool output,
    # which is a deterministic lookup, not a similarity ranking.


class ResearchPlan(BaseModel):
    collection_top_k: dict[str, int]
    # How many chunks to pull from each Qdrant collection, e.g. {"docs": 4, "incidents": 3}.

    use_ast_tools: bool = False
    # Whether the Retriever should also query the AST dependency MCP server.

    use_github_tools: bool = False
    # Whether the Retriever should also fetch real source text for AST-matched
    # components via the GitHub MCP server (see mcp_clients/github_client.py).
    # Only meaningful alongside use_ast_tools=True — it's the AST lookup's own
    # file_paths that this step fetches.

    rationale: str = ""
    # One line saying why this plan — kept so the audit trail can explain the retrieval.


# ---------------------------------------------------------------------------
# GraphState
# ---------------------------------------------------------------------------
# THE MOST IMPORTANT SCHEMA IN THIS FILE.
#
# In LangGraph, every node in your graph is just a Python function that
# receives the current state, does some work, and returns updates to that
# state. This class defines exactly what "the current state" contains at
# every point in the pipeline, from the moment a question comes in to the
# moment a DecisionBrief is produced.
#
# Think of GraphState as a single folder that gets passed from person to
# person (node to node) in an office. Each person adds their own notes to
# the folder, but the folder itself never changes shape — everyone knows
# where to look for the question, where to write their findings, etc.
class GraphState(BaseModel):
    # --- Set once, at the very start, and never changed afterward ---
    question: str
    pipeline_mode: PipelineMode

    # --- Stamped by input_guardrail; read by memory_write to compute latency_ms ---
    started_at: Optional[float] = None
    # time.perf_counter() at the moment the run began. A monotonic clock
    # reading only makes sense within the process that took it, so this is
    # bookkeeping for this one graph run, not something later persisted itself.

    # --- Set by input_guardrail; read by route_after_input_guardrail/escalate ---
    blocked: bool = False
    block_reason: str = ""
    # Set together when input_guardrail rejects the question outright (looks
    # like it contains PII) before any retrieval or LLM call happens. Routes
    # straight to escalate() instead of supervisor — see graph.py.

    # --- Set by the Supervisor Agent (first real node after guardrails) ---
    question_type: Optional[str] = None
    # e.g. "business_functional", "incident_rca", "impact_analysis"
    # The Supervisor reads the question and classifies it into one of your
    # three build-scope types, which determines which domain(s) to search.

    target_component: Optional[str] = None
    # e.g. "OrderService" — populated for Impact Analysis questions so the
    # custom MCP server knows which node to start the dependency walk from.

    # --- Filled in by the Research + Retriever step ---
    research_plan: Optional[ResearchPlan] = None
    # Set by Research (which sources, how many chunks); read by Retriever.

    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    # Chunks pulled from Qdrant (docs/incidents) and/or raw tool output
    # (MCP/AST code queries), each tagged with where it came from. Turning
    # these into structured, cited claims is the Evidence Agent's job, not
    # the Retriever's — the Retriever only fetches.

    retrieval_errors: list[str] = Field(default_factory=list)
    # Anything that went wrong while fetching (Qdrant down, MCP server dead,
    # no component identified). Retrieval never raises; it records the problem
    # here and carries on with whatever it did get, so the graph can degrade
    # to an honest escalation instead of crashing or bluffing.

    # --- Filled in by the Evidence Agent ---
    evidence: list[EvidenceRecord] = Field(default_factory=list)

    # --- Filled in by the Critic Agent (skipped entirely in CRITIC_OFF/BASELINE modes) ---
    critique_flags: list[CritiqueFlag] = Field(default_factory=list)

    # --- Filled in / updated by the Confidence Gate ---
    confidence_score: float = 0.0
    # A 0.0–1.0 heuristic score. See graph.py for exactly how this is
    # computed — kept as a plain float here, not a separate class, because
    # the SCORE itself isn't really the auditable artifact; the
    # `confidence_rationale` string inside DecisionBrief is.

    # --- Used to enforce the retry cap on the Critic -> Research loop ---
    retry_count: int = 0
    # Every time the Critic sends the state back to Research for another
    # look, this increments by 1. The graph's conditional edge checks
    # `retry_count < 2` before allowing another loop, so a stubborn
    # contradiction can't cause an infinite loop (and an infinite bill).

    # --- The final output, once Synthesis has run ---
    decision_brief: Optional[DecisionBrief] = None

    agent_errors: list[str] = Field(default_factory=list)
    # A failed LLM call in Evidence or Critic (API error, unparseable output).
    # Same principle as retrieval_errors: recorded, never raised, and the gate
    # treats any of them as "can't be confident" and escalates.

    # --- Appended to by every node, in execution order ---
    trace: list[str] = Field(default_factory=list)
    # One entry per node actually executed, in order — including repeats from
    # the Critic -> Research retry loop. `memory_write` prints the full list
    # at the end of every run so a single log line shows the exact path this
    # question took (e.g. a retry shows up as "research" appearing twice, not
    # just as a retry_count number). Each node returns `state.trace + [name]`
    # rather than mutating in place, matching how token_usage/llm_calls
    # already accumulate through the graph.

    # --- Populated at the very end, for the audit trail + eval harness ---
    token_usage: int = 0
    # Chat-model tokens (input + output) summed over every LLM call so far.
    # Embedding calls are not counted here (negligible, and priced differently).
    llm_calls: int = 0
    # Number of LLM calls made — the simplest measure of what the Critic
    # (and each retry) adds, alongside token_usage and latency.
    latency_ms: float = 0.0
    # These aren't "agent" fields — nothing upstream reasons about them.
    # They're bookkeeping, added up as the state flows through each node,
    # so the eval harness can compare cost/latency across pipeline_modes
    # without needing separate instrumentation code.


# ---------------------------------------------------------------------------
# A quick manual sanity check you can run directly:
#     python app/schemas.py
# This isn't a real test suite (that comes later) — it's just proof that
# the schema above is valid and behaves the way you'd expect, useful while
# you're still learning how Pydantic validation works.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    state = GraphState(
        question="How does OrderFlow handle a payment gateway timeout?",
        pipeline_mode=PipelineMode.CRITIC_ON,
    )
    print("Created a fresh GraphState:")
    print(state.model_dump_json(indent=2))

    # Try creating one that SHOULD fail, to see Pydantic's validation in action:
    try:
        GraphState(question="test", pipeline_mode="not_a_real_mode")
    except Exception as exc:
        print("\nExpected validation error (this is Pydantic working correctly):")
        print(exc)
