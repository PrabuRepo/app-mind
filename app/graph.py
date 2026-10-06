"""
graph.py — the LangGraph skeleton for AppMind.

WHAT IS LANGGRAPH, IN ONE PARAGRAPH:
LangGraph lets you describe a multi-step AI workflow as a graph of "nodes"
(plain Python functions) connected by "edges" (which node runs next). Unlike
a simple linear script, LangGraph supports CONDITIONAL edges — after a node
runs, a routing function inspects the current state and decides which node
should run next, out of several options. That's exactly what we need here:
after the Critic runs, we need to decide "go back to Research" or "move on
to the Confidence Gate," and that decision depends on what the Critic found.

TODAY'S GOAL (Day 1 AM):
Every node below is a STUB — it does the minimum to prove the graph's
shape and routing logic work, without making any real LLM calls or
database queries yet. Day 3 replaces each stub's *insides* with real logic;
the graph's *shape* (which nodes exist, which edges connect them, how
pipeline_mode changes the path) is decided now and shouldn't need to change
later. Getting the shape right today is the whole point of building the
skeleton before the real logic.
"""

from __future__ import annotations

import time

from langgraph.graph import StateGraph, END

from agents.critic import review_evidence
from agents.evidence import extract_evidence
from agents.synthesis import synthesize_answer, synthesize_baseline_answer
from app.component_hints import component_hint
from app.retrieval import make_plan, retrieve
from app.schemas import (
    CritiqueFlag,
    CritiqueFlagType,
    DecisionBrief,
    EvidenceRecord,
    GraphState,
    PipelineMode,
)
from guardrails.input_guardrail import input_guardrail
from guardrails.output_guardrail import output_guardrail
from memory.memory_write import memory_write


# ===========================================================================
# NODES
# ===========================================================================
# Every function below has the same shape, because this is what LangGraph
# requires: it takes the current GraphState in, and returns a dict of the
# fields it wants to UPDATE (not the whole state — LangGraph merges your
# returned dict into the existing state for you). This matters: if a node
# doesn't touch `evidence`, it simply doesn't include "evidence" in its
# return dict, and the existing value is left alone.


def supervisor(state: GraphState) -> dict:
    """
    Classifies the question into one of your three build-scope types, and
    for Impact Analysis and Incident RCA questions, guesses which code
    component the question is actually about (fallback only — AST's own
    name matching against the question text, see mcp_clients/ast_client.py,
    takes priority when it finds an explicit match; this only kicks in when
    the question is phrased in business language that never names the
    component literally, e.g. "charged twice" rather than "PaymentClient").

    The component guess comes from the application profile's `scope.aliases`
    (app/component_hints.py), so no application's names live in this file.
    The type classification is still a crude keyword check standing in for
    what will eventually be an LLM classification call. It is intentionally
    primitive — the POINT of a stub is that it's obviously not the real
    logic, so nobody mistakes it for a finished feature.
    """
    q_lower = state.question.lower()
    if "affect" in q_lower or "depend" in q_lower or "break" in q_lower:
        question_type = "impact_analysis"
    elif "incident" in q_lower or "charge" in q_lower or "bug" in q_lower:
        question_type = "incident_rca"
    else:
        question_type = "business_functional"

    # Only these two types read the code graph, so only they need a component.
    target_component = component_hint(state.question) if question_type != "business_functional" else None

    print(f"[supervisor] classified as: {question_type}")
    return {
        "question_type": question_type,
        "target_component": target_component,
        "trace": state.trace + ["supervisor"],
    }


def research(state: GraphState) -> dict:
    """
    Decides WHERE to look: which Qdrant collections, how many chunks from
    each, and whether the MCP/AST code tools are needed. It only PLANS — the
    Retriever node next executes the plan. This node is also where a
    Critic-triggered retry lands: it reads `retry_count` and widens the
    search on a retry, since asking the same narrow question again would
    just return the same evidence.

    REAL (no LLM): the plan is a deterministic function of question_type and
    retry_count — see `make_plan` in app/retrieval.py.
    """
    plan = make_plan(state.question_type, state.retry_count)
    print(f"[research] {plan.rationale}")
    step = f"research (retry {state.retry_count})" if state.retry_count else "research"
    return {"research_plan": plan, "trace": state.trace + [step]}


def retriever(state: GraphState) -> dict:
    """
    Executes the research plan: vector search over `docs` + `incidents` in
    Qdrant and, for impact questions, calls to the AST dependency MCP server.
    Fetches only — turning chunks into cited claims is the Evidence node's job.

    Never raises: anything that fails (Qdrant down, MCP server dead, embedding
    error) is recorded in `retrieval_errors` and whatever WAS retrieved still
    flows on. BASELINE mode enters here directly (it skips Research), so with
    no plan in state it falls back to the same first-pass plan the other
    modes start with — every mode sees the same retrieval, so the eval
    isolates the Evidence/Critic/Gate steps rather than a retrieval gap.
    """
    plan = state.research_plan or make_plan(state.question_type, state.retry_count)
    result = retrieve(state.question, plan, state.target_component)
    by_collection = {c: sum(1 for ch in result.chunks if ch.collection == c) for c in ("docs", "incidents", "code")}
    print(f"[retriever] {len(result.chunks)} chunk(s) {by_collection}, {len(result.errors)} error(s)")
    for err in result.errors:
        print(f"[retriever] WARNING: {err}")
    mcp_slugs = []
    for mcp_call in result.mcp_calls:
        print(f"[mcp] {mcp_call} invoked")
        mcp_slugs.append(f"mcp:{mcp_call.split()[0].lower()}")   # "AST MCP" -> "mcp:ast"
    code_index = []
    if result.snapshot is not None:
        print(f"[code-index] {result.snapshot.repo}@{result.snapshot.sha[:7]} "
              f"indexed_at={result.snapshot.indexed_at.isoformat(timespec='seconds')}")
        code_index = ["code-index"]
    # "llm:embedding" is unconditional: _search_vector_collections() calls
    # embed_query() as the very first thing retrieve() does, every time,
    # regardless of question type or whether the search that follows it
    # succeeds — see app/retrieval.py.
    return {
        "retrieved_chunks": result.chunks,
        "retrieval_errors": result.errors,
        "target_component": result.target_component,
        "trace": state.trace + ["retriever", "llm:embedding"] + mcp_slugs + code_index,
    }


def evidence(state: GraphState) -> dict:
    """
    Turns retrieved chunks into structured, cited EvidenceRecords: one LLM
    call extracts claims with verbatim quotes, then code checks each quote
    really appears in the cited chunk and sets `grounded` from that check
    (see agents/evidence.py). It reports what each source asserts — it does not
    judge or reconcile them; that is the Critic's job.

    On an LLM failure it records the error and returns no evidence, so the
    gate escalates instead of the graph crashing. Each pass REPLACES
    `agent_errors`, so a stale error from a previous retry can't linger.
    """
    result = extract_evidence(state.question, state.retrieved_chunks)
    ungrounded = sum(1 for r in result.items if not r.grounded)
    print(f"[evidence] {len(result.items)} claim(s), {ungrounded} ungrounded"
          + (f", ERROR: {result.error}" if result.error else ""))
    # No "llm:evidence" trace entry when llm_calls==0 — extract_evidence()
    # short-circuits with zero chunks (see agents/evidence.py) without ever
    # calling the LLM, and the trace should reflect what actually ran.
    trace_step = ["evidence", "llm:evidence"] if result.llm_calls else ["evidence"]
    return {
        "evidence": result.items,
        "agent_errors": [f"evidence: {result.error}"] if result.error else [],
        "token_usage": state.token_usage + result.tokens,
        "llm_calls": state.llm_calls + result.llm_calls,
        "trace": state.trace + trace_step,
    }


def critic(state: GraphState) -> dict:
    """
    Reviews the evidence for contradictions, uncited claims, and gaps.
    THIS NODE IS THE WHOLE POINT OF YOUR COMPARATIVE EVAL — the difference
    between critic_on and critic_off runs is entirely whether this node
    executes at all (see `build_graph()`'s conditional edges below).

    One LLM call with a deliberately GENERIC prompt (agents/critic.py): it
    defines the three flag types in general terms and never names a specific
    incident, so the eval measures real judgement, not a critic tuned to the
    test corpus. It re-reads the evidence from scratch on every pass, so a
    flag that a retry's wider evidence resolves simply isn't raised again.

    If the Critic itself fails, that is recorded in `agent_errors` and the
    gate escalates: evidence nobody could review must not pass as clean.
    """
    result = review_evidence(state.question, state.evidence, state.critique_flags)
    for flag in result.items:
        status = "resolved" if flag.resolved else "OPEN"
        print(f"[critic] FLAG {status} ({flag.flag_type.value}): {flag.description}")
    print(f"[critic] {len(result.items)} flag(s)" + (f", ERROR: {result.error}" if result.error else ""))
    # Same reasoning as evidence's trace_step: review_evidence() short-circuits
    # with zero evidence, no LLM call made — see agents/critic.py.
    trace_step = ["critic", "llm:critic"] if result.llm_calls else ["critic"]
    update = {
        "critique_flags": result.items,
        "token_usage": state.token_usage + result.tokens,
        "llm_calls": state.llm_calls + result.llm_calls,
        "trace": state.trace + trace_step,
    }
    if result.error:
        update["agent_errors"] = state.agent_errors + [f"critic: {result.error}"]
    return update


def confidence_gate(state: GraphState) -> dict:
    """
    Computes a confidence score from what's been gathered so far, and the
    graph's routing logic (see `route_after_gate` below) uses this score,
    plus whether any critique flags are still unresolved, to decide whether
    to proceed to Synthesis or escalate to a human.

    STUBBED TODAY: a simple heuristic — starts at 1.0, subtracted for every
    unresolved critique flag. This heuristic IS mostly the real logic
    already; a heuristic confidence score is genuinely fine for this
    project (you don't need a trained model here), so this stub is closer
    to "done" than the others.
    """
    unresolved = [f for f in state.critique_flags if not f.resolved]
    score = max(0.0, 1.0 - 0.3 * len(unresolved))
    if state.evidence:
        # Citation coverage: the share of claims whose quote was verified
        # against its source. Applies in critic_off too — grounding is part of
        # the Evidence step, not the Critic.
        score *= sum(e.grounded for e in state.evidence) / len(state.evidence)
    if state.retrieval_errors or state.agent_errors:
        # A retrieval source or an LLM agent failed, so the evidence set is
        # known to be incomplete or unreviewed. Cap below the 0.5 escalation
        # threshold: answering as if nothing were missing is the false
        # confidence this project exists to avoid.
        score = min(score, 0.4)
    if not state.evidence:
        # Nothing was retrieved (empty result, or every source failed): there
        # is nothing to stand on, so never be confident — escalate instead.
        score = 0.0
    print(f"[confidence_gate] score={score:.2f}, unresolved_flags={len(unresolved)}, "
          f"evidence={len(state.evidence)}")
    return {"confidence_score": score, "trace": state.trace + ["confidence_gate"]}


def escalate(state: GraphState) -> dict:
    """
    Reached when confidence is too low or flags are unresolved after the
    retry cap is hit. Produces a DecisionBrief that HONESTLY says "escalate
    to a human," rather than forcing out a low-confidence answer — this is
    core to your project's framing ("capture and scale SME judgment," not
    paper over uncertainty).

    ALSO reached directly from input_guardrail when the question was blocked
    (looks like it contains PII) — same "honest brief instead of proceeding"
    shape, just a different reason and no evidence to reference.
    """
    trace = state.trace + ["escalate"]
    if state.blocked:
        print(f"[escalate] input blocked: {state.block_reason}")
        brief = DecisionBrief(
            # Must contain "escalate" (lowercased) — output_guardrail's own
            # zero-citations check uses that as its escalation signal, same
            # as the confidence-based path below.
            answer="AppMind escalated this question instead of investigating it.",
            citations=[],
            confidence_rationale=f"Blocked before investigation began: {state.block_reason}.",
        )
        return {"decision_brief": brief, "trace": trace}

    print("[escalate] confidence too low or unresolved flags remain — escalating to human")
    brief = DecisionBrief(
        answer="AppMind could not reach sufficient confidence to answer automatically.",
        citations=state.evidence,
        confidence_rationale=(
            f"confidence_score={state.confidence_score:.2f}, "
            f"{len(state.critique_flags)} critique flag(s) present, "
            f"{len(state.evidence)} evidence record(s) — escalated per policy."
            + "".join(f" Unresolved {f.flag_type.value}: {f.description}"
                      for f in state.critique_flags if not f.resolved)
            + (f" Retrieval problems: {'; '.join(state.retrieval_errors)}" if state.retrieval_errors else "")
            + (f" Agent problems: {'; '.join(state.agent_errors)}" if state.agent_errors else "")
        ),
    )
    return {"decision_brief": brief, "trace": trace}


def synthesis(state: GraphState) -> dict:
    """
    Produces the final DecisionBrief when confidence IS sufficient. This is
    the node that runs for a "successful" investigation, as opposed to
    `escalate` above.

    Two paths, matching how this node is reached: BASELINE arrives with no
    `evidence` at all (Evidence never ran for that mode — see
    route_after_supervisor/route_after_retriever) and answers straight from
    `retrieved_chunks`, unverified; critic_off/critic_on arrive with verified
    EvidenceRecords and answer from those only (see agents/synthesis.py).
    """
    if state.evidence:
        result = synthesize_answer(state.question, state.evidence)
        llm_label = "llm:synthesis"
    else:
        result = synthesize_baseline_answer(state.question, state.retrieved_chunks)
        llm_label = "llm:synthesis_baseline"

    # No llm: entry when llm_calls==0 — both synthesize_* functions
    # short-circuit on empty input without calling the LLM (see agents/synthesis.py).
    trace_step = ["synthesis", llm_label] if result.llm_calls else ["synthesis"]
    update = {
        "token_usage": state.token_usage + result.tokens,
        "llm_calls": state.llm_calls + result.llm_calls,
        "trace": state.trace + trace_step,
    }

    if result.error or not result.answer:
        # The confidence gate already judged this investigation good enough
        # to proceed (or BASELINE has no gate at all), but the answer-writing
        # call itself then failed — a genuine, if rare, extra failure mode.
        # There's no edge back to `escalate` from here (see build_graph()), so
        # we downgrade confidence and say so honestly in place, rather than
        # shipping a brief that still carries the earlier high confidence for
        # content that was never actually written.
        print(f"[synthesis] LLM error, degrading confidence and stating so: {result.error}")
        update["confidence_score"] = min(state.confidence_score, 0.3)
        update["agent_errors"] = state.agent_errors + [f"synthesis: {result.error or 'no answer produced'}"]
        update["decision_brief"] = DecisionBrief(
            answer="AppMind gathered evidence but could not compose an answer due to an internal error.",
            citations=result.citations or state.evidence,
            confidence_rationale=f"synthesis failed: {result.error or 'no answer produced'}",
        )
        return update

    print(f"[synthesis] producing final decision brief ({result.llm_calls} LLM call(s))")
    update["decision_brief"] = DecisionBrief(
        answer=result.answer,
        citations=result.citations,
        confidence_rationale=f"confidence_score={state.confidence_score:.2f}, no blocking flags",
        affected_components=[state.target_component] if state.target_component else None,
    )
    return update


# input_guardrail, output_guardrail and memory_write are no longer defined
# here — they're imported above from guardrails/ and memory/. They still
# register as graph nodes exactly like the functions below (see build_graph()).


# ===========================================================================
# CONDITIONAL ROUTING FUNCTIONS
# ===========================================================================
# These are NOT nodes — they don't touch the state's data. They're small
# functions that LangGraph calls right after a given node finishes, and
# their return value (a string) tells LangGraph which node to run next.
# This is the mechanism that makes the graph a graph rather than a straight
# line: the SAME node (e.g. `critic`) can lead to different next steps
# depending on what's in the state.


def route_after_input_guardrail(state: GraphState) -> str:
    """
    Blocked input (looks like it contains PII) skips straight to escalate —
    no retrieval, no LLM calls. That's the whole point of an input guardrail:
    catch bad input before spending money on it, not after.
    """
    return "escalate" if state.blocked else "supervisor"


def route_after_supervisor(state: GraphState) -> str:
    """
    This is where `pipeline_mode` does its main job: BASELINE mode skips the
    Research planning step and goes straight to the Retriever, then (see
    `route_after_retriever`) directly to a simplified synthesis step, bypassing
    Evidence/Critic/Gate. It DOES retrieve — a baseline with no context would
    be a strawman. The other two modes proceed through the real pipeline and
    get split further downstream (see `route_after_evidence` below).
    """
    if state.pipeline_mode == PipelineMode.BASELINE:
        return "retriever"  # baseline: retrieve -> answer, no evidence/critic/gate
    return "research"


def route_after_retriever(state: GraphState) -> str:
    """
    BASELINE has retrieved and now answers directly; every other mode goes on
    to the Evidence node.
    """
    if state.pipeline_mode == PipelineMode.BASELINE:
        return "synthesis"
    return "evidence"


def route_after_evidence(state: GraphState) -> str:
    """
    This is the SECOND place `pipeline_mode` matters: critic_off skips the
    critic node entirely and goes straight to the confidence gate.
    critic_on runs the critic. (BASELINE never reaches this function at
    all, because route_after_supervisor already sent it straight to
    synthesis.)
    """
    if state.pipeline_mode == PipelineMode.CRITIC_OFF:
        return "confidence_gate"
    return "critic"  # CRITIC_ON


def route_after_critic(state: GraphState) -> str:
    """
    The retry loop. If there are unresolved flags AND we haven't hit the
    retry cap yet, go back to `research` for another attempt. Otherwise,
    move on to the confidence gate regardless of how it turned out — the
    gate is what decides escalate vs. synthesis, not this function.

    The retry cap (`retry_count < 2`) is what prevents an infinite loop (and
    an infinite API bill) if the Critic keeps finding the same problem.
    """
    unresolved = any(not f.resolved for f in state.critique_flags)
    if unresolved and state.retry_count < 2:
        return "research_retry"
    return "confidence_gate"


def route_after_gate(state: GraphState) -> str:
    """
    The final fork: does this investigation get a real answer, or does it
    get escalated to a human? A simple fixed threshold (0.5) is used here —
    tune this once you have real confidence scores from Day 2's real Critic
    logic; a stub's score isn't meaningful enough to tune against yet.
    """
    unresolved = any(not f.resolved for f in state.critique_flags)
    if state.confidence_score < 0.5 or unresolved:
        return "escalate"
    return "synthesis"


def _research_retry_wrapper(state: GraphState) -> dict:
    """
    A tiny helper node whose ONLY job is to increment retry_count before
    control passes back to the real `research` node. Kept separate from
    `research` itself so `research`'s own logic doesn't need to know
    whether it's being called fresh or as a retry — it just always
    increments the counter it's handed.
    """
    return {"retry_count": state.retry_count + 1}


# ===========================================================================
# GRAPH ASSEMBLY
# ===========================================================================
def build_graph():
    """
    Wires every node and edge above into an executable LangGraph. Read this
    function alongside the flow diagram in your one-pager — every arrow in
    that diagram should correspond to either a fixed `add_edge` call or a
    conditional routing function below.
    """
    graph = StateGraph(GraphState)

    # Register every node. The string name is what edges/routing functions
    # refer to below — it does NOT have to match the Python function name,
    # but keeping them identical (as done here) avoids confusion.
    graph.add_node("input_guardrail", input_guardrail)
    graph.add_node("supervisor", supervisor)
    graph.add_node("research", research)
    graph.add_node("research_retry", _research_retry_wrapper)
    graph.add_node("retriever", retriever)
    graph.add_node("evidence", evidence)
    graph.add_node("critic", critic)
    graph.add_node("confidence_gate", confidence_gate)
    graph.add_node("escalate", escalate)
    graph.add_node("synthesis", synthesis)
    graph.add_node("output_guardrail", output_guardrail)
    graph.add_node("memory_write", memory_write)

    # Entry point: every run starts at input_guardrail.
    graph.set_entry_point("input_guardrail")

    # Fixed edges (always go from A to B, no branching):
    graph.add_edge("escalate", "output_guardrail")
    graph.add_edge("synthesis", "output_guardrail")
    graph.add_edge("output_guardrail", "memory_write")
    graph.add_edge("memory_write", END)

    # research_retry always loops back into research after incrementing the counter.
    graph.add_edge("research_retry", "research")
    # research always proceeds to the retriever (no branching needed here).
    graph.add_edge("research", "retriever")

    # Conditional edges — this is where pipeline_mode and the retry logic live.
    graph.add_conditional_edges(
        "input_guardrail",
        route_after_input_guardrail,
        {"escalate": "escalate", "supervisor": "supervisor"},
    )
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {"research": "research", "retriever": "retriever"},
    )
    graph.add_conditional_edges(
        "retriever",
        route_after_retriever,
        {"evidence": "evidence", "synthesis": "synthesis"},
    )
    graph.add_conditional_edges(
        "evidence",
        route_after_evidence,
        {"critic": "critic", "confidence_gate": "confidence_gate"},
    )
    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {"research_retry": "research_retry", "confidence_gate": "confidence_gate"},
    )
    graph.add_conditional_edges(
        "confidence_gate",
        route_after_gate,
        {"escalate": "escalate", "synthesis": "synthesis"},
    )

    return graph.compile()


# ===========================================================================
# MANUAL SMOKE TEST
# ===========================================================================
# Run this file directly (`python app/graph.py`) to see the whole skeleton
# execute end-to-end for all three pipeline_modes. This is exactly the
# "exit criterion" for Day 1 AM in your implementation plan: the graph runs
# with stubbed nodes returning fake data, proving the SHAPE is correct
# before any real logic is written.
if __name__ == "__main__":
    app = build_graph()

    for mode in PipelineMode:
        print(f"\n{'=' * 60}\nRunning pipeline_mode = {mode.value}\n{'=' * 60}")
        start = time.time()
        initial_state = GraphState(
            question="What would be affected if we changed OrderService's retry logic?",
            pipeline_mode=mode,
        )
        result = app.invoke(initial_state)
        elapsed_ms = (time.time() - start) * 1000
        print(f"\nFinal answer: {result['decision_brief'].answer}")
        print(f"Confidence: {result['confidence_score']:.2f}")
        print(f"(stub run took {elapsed_ms:.1f}ms)")
