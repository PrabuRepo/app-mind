"""
ui/app.py — the Streamlit front end.

V1, deliberately minimal per CLAUDE.md ("single page, question box, brief
output with citations, nothing else") and the user's own steer: start
simple, add capabilities later. Always runs pipeline_mode=CRITIC_ON ("AppMind
proper") — no mode selector yet. A mode selector, critique-flag display,
retrieval/agent-error display, and a cost/latency footer are a deliberate
fast-follow (logged in TASKS.md), not forgotten: all of that data already
exists on GraphState, so adding it later is cheap.

    streamlit run ui/app.py

Calls the graph in-process via app/investigate.py — no separate FastAPI
layer. CLAUDE.md's own "what's not built yet" list never mentions one; only
impl-plan.md's older tech-stack section does, and it's stale on this point
(CLAUDE.md is authoritative, per its own header). Going through
app/investigate.py (rather than build_graph().invoke() directly) means a
repeated question is answered from the Redis cache instead of re-running the
whole pipeline — see that module's docstring for why the eval harness
deliberately does not get this same shortcut.
"""

from __future__ import annotations

import streamlit as st

from app.investigate import investigate
from app.schemas import PipelineMode

st.set_page_config(page_title="AppMind", page_icon="\U0001f9e0")


def _escalated(confidence_rationale: str) -> bool:
    # Same signal evals/run_eval.py uses: escalate()'s confidence_rationale
    # always contains this exact phrase, unlike synthesis()'s.
    return "escalated per policy" in confidence_rationale


st.title("AppMind")
st.caption(
    "Ask a question about OrderFlow. AppMind investigates, cites its sources, "
    "and escalates instead of guessing when it isn't confident enough."
)

with st.form("question_form"):
    question = st.text_area(
        "Your question",
        placeholder="e.g. Why were customers charged twice for one order?",
    )
    submitted = st.form_submit_button("Investigate")

if submitted:
    if not question.strip():
        st.warning("Enter a question first.")
    else:
        with st.spinner("Investigating... (can take up to ~15 seconds)"):
            try:
                brief = investigate(question.strip(), PipelineMode.CRITIC_ON)
                st.session_state["last_brief"] = brief
                st.session_state["last_question"] = question.strip()
            except Exception as exc:  # the graph itself never raises by design (see FAILURES.md) —
                # this is a last-resort net so a genuinely unexpected error shows a message
                # instead of a raw traceback mid-demo.
                st.error(f"Something went wrong: {type(exc).__name__}: {exc}")

if "last_brief" in st.session_state:
    brief = st.session_state["last_brief"]

    st.subheader("Question")
    st.write(st.session_state["last_question"])

    st.subheader("Answer")
    if _escalated(brief.confidence_rationale):
        st.warning(brief.answer)
    else:
        st.write(brief.answer)
    st.caption(brief.confidence_rationale)

    if brief.affected_components:
        st.markdown(f"**Affected components:** {', '.join(brief.affected_components)}")

    st.subheader("Citations")
    if not brief.citations:
        st.write("No citations.")
    else:
        for citation in brief.citations:
            location = f" — {citation.location}" if citation.location else ""
            st.markdown(f"**{citation.source}**{location}")
            st.write(citation.claim)
            st.divider()
