# AppMind — Application Knowledge & Decision Intelligence Agent

## 1. Problem Statement

Teams that own applications depend on knowledge scattered across business documentation, architecture/design documents, source code, APIs, runbooks, incidents, and tickets. Critical knowledge is often implicit in experienced SMEs, creating bottlenecks when teams need to investigate an issue, evaluate a design, or make a decision about the application.

In practice, an application team asks the same kinds of questions repeatedly across the software development lifecycle — not only "why did this break," but also "how does this work" and "what would break if we changed X." Today, answering any of these well requires finding the right person, not the right system.

AppMind is an application-specific AI investigation and decision system that consolidates this scattered knowledge and investigates questions on the team's behalf, producing an evidence-backed, auditable decision brief — and escalating to a human SME when evidence is insufficient or contradictory. It is explicitly framed to capture and scale SME judgment, not replace SMEs.

Narrow build scope (not "any question, any application"): one named application, three question types — (1) one Business/Functional question, (2) one Incident/RCA question with a known planted root cause, and (3) one Impact Analysis question requiring code-dependency traversal.

### Use cases

**Architecture/behavior Q&A with citations ("how does this work")**

Ask it questions like "how does the auth flow handle token refresh" or "what happens if the payment webhook times out," answered strictly from architecture docs + source code with cited evidence. This is your cleanest Baseline-RAG vs. AppMind comparison, since it isolates whether the agentic Research→Evidence→Critic loop actually beats plain retrieval on accuracy.

**Change-impact / "will this fit" review**

Give it a proposed design or code change (a PR description or a short design doc) and have it evaluate compatibility against existing architecture, API contracts, and prior related decisions — surfacing conflicts or unstated assumptions, and escalating if evidence is ambiguous. Good showcase for the Challenger/Critic agent, since planted inconsistencies here directly test the Error-Catch and False-Confidence metrics.

**Blast-radius / dependency analysis ("what breaks if we change X")**

Using the code dependency graph, ask "what services/tests would be affected if we change this schema/interface." This is the most mechanical of the four (closer to static analysis than reasoning), but it's a good POC because it's easy to verify correctness objectively and cheap to demo.

## 2. Proposed Solution & Architecture

AppMind follows the investigation flow:

> Question → Hypotheses → Evidence → Validation → Challenge → Confidence → Decision

A Supervisor Agent coordinates Research, Evidence, and Challenger/Critic agents. RAG provides access to application knowledge, while MCP provides access to tools and live application information. The Critic can trigger additional research when evidence gaps, contradictions, or unsupported conclusions are identified. Validated investigations are synthesized into a decision brief and persisted as both an audit trail and reusable application memory.

**Application Knowledge:** Business | Architecture | Source Code | APIs | Operations | Incidents | Tickets / Decisions | Code dependency graph (for impact analysis)

## 3. Data Surface

The system will use a bounded knowledge base for one specific application, containing representative business, technical, and operational artifacts. This may include architecture documents, API documentation, source code, runbooks, incident reports, tickets, and historical decisions.

The system will also consume tools through MCP, including an existing MCP server and one custom MCP server for application-specific information or investigation data.

## 4. Evaluation & Comparative Approaches

The project will compare:

- **Baseline:** RAG-based application question answering — Retrieve → Answer.
- **AppMind:** Agentic investigation with Research → Evidence Validation → Critic → Confidence Gate → Synthesis.

A key experiment will additionally compare AppMind with Critic vs. without Critic to determine whether the critique stage materially improves reliability.

## 5. Success Metrics

Primary quantitative metrics will include:

- **Retrieval Recall@K** — ability to retrieve relevant application evidence.
- **Citation / Evidence Accuracy** — whether claims are supported by cited sources.
- **Error-Catch Rate** — ability of the Critic to identify planted errors or contradictions.
- **False-Confidence Rate** — frequency of confidently produced conclusions when evidence is insufficient.
- **Escalation Accuracy** — whether genuinely unresolved cases are appropriately escalated.

Qualitative evaluation will assess decision usefulness, reasoning transparency, and auditability using an LLM-as-a-Judge with a defined evaluation rubric.

## 6. Frameworks & Technology

- **LangGraph** — explicit stateful orchestration and iterative Research → Evidence → Critic workflow.
- **MCP SDK** — standardized access to application tools and live information.
- **Pydantic** — structured evidence, critique, confidence, and decision-brief schemas.
- **FastAPI / Python** — application backend.
- **Qdrant or pgvector** — application knowledge retrieval.
- **PostgreSQL** — decision briefs, investigation history, and application memory.
- **Redis** — session/context management.
- **Streamlit** — lightweight user interface.
- **OpenAI/Anthropic API + Docker** — model integration and deployment.

## 7. Expected Outcome

The project will demonstrate whether an agentic, evidence-validation and critique-driven workflow can produce more reliable and auditable application decisions than a conventional RAG baseline, while explicitly identifying uncertainty and escalating unresolved investigations to human SMEs.
