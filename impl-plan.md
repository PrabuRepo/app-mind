# AppMind — Implementation Plan (2-Day Compressed)

**Timeline: today + tomorrow, then submit.** This is a hard cut from the earlier 4-day version — scope drops accordingly. Everything below is the minimum that still satisfies the rubric (problem definition, data processing incl. PII, system design incl. trade-offs, evals incl. error-handling/cost/latency) and your mandatory Critic comparison. Nothing here is aspirational — if it's listed, it's load-bearing.

**Confirmed decisions carried forward:**

- Code domain: **MCP/AST search, not RAG.**
- RAG domains: **docs + incidents only** (2, not 3 — tickets folded out entirely, not just folded into docs, to protect time). If your incident data can double as tickets content, keep 2; do not source a 3rd domain.
- Eval: three `pipeline_mode`s (`baseline`, `critic_off`, `critic_on`) on one graph.
- Demo questions: 3, one per build-scope type (Business/Functional, Incident/RCA with planted root cause, Impact Analysis via dependency graph).

---

## Day 1 (today) — everything must run end-to-end by end of day, even if rough

| Block | What | Cut if behind |
| --- | --- | --- |
| **AM** | `schemas.py` (below) + Docker up (Postgres, Qdrant, Redis) + LangGraph skeleton with stubbed nodes, `pipeline_mode` wired | Nothing — this is the spine, do not skip |
| **Midday** | Ingestion: docs + incidents into Qdrant, 2 collections, \~10–15 source docs total, one incident deliberately containing the planted root cause | Trim source count to \~8 if sourcing is slow — quality over volume |
| **PM** | MCP servers: GitHub (existing) + custom dependency-graph (AST walk → static JSON/table, queried by MCP tool) | If the custom server slips, hardcode a small dependency map for your one target component as a stopgap — state this as a known limitation in `FAILURES.md`, don't lose the whole Impact Analysis question |
| **EOD** | Real logic for Research → Retriever → Evidence → Synthesis (skip Critic realism today, stub it returning "no issues") | — |

**Redis, Streamlit polish, reranker, HyDE, memory-read-reuse, impact-analysis as a separate branch: not attempted.** Redis is up but unused beyond a trivial cache; UI is functional-only.

---

## Day 2 (tomorrow) — build eval, write docs, cut everything not needed for submission

| Block | What | Cut if behind |
| --- | --- | --- |
| **AM** | Real Critic logic + Confidence Gate (heuristic: citation coverage + Critic-clean pass) + audit trail write (Postgres) | If Critic logic is shaky, ship a simpler version: single LLM call checking evidence list against 3 fixed contradiction patterns rather than open-ended critique |
| **Midday** | Eval harness: run 3 demo questions + a small backing set (\~6–8 questions total, not 10–15 — compressed timeline) through all 3 `pipeline_mode`s. Log token usage + wall-clock time per run for cost/latency. Add 2 error-handling cases (bad tool call, empty retrieval) and confirm graceful escalation instead of crash | If backing set can't be sourced, run demo-question-set only and say explicitly in docs this is qualitative not statistically powered |
| **PM** | Streamlit: single page, question box, brief output with citations — nothing else | Skip audit-trail viewer in UI if short on time; the Postgres table existing and being queryable is enough for the rubric |
| **EOD** | Docs (4–5 pages): include explicit **PII statement**, explicit **Trade-offs section**, cost/latency table, error-catch/false-confidence table across the 3 modes. Demo video (3 min). Finalize `FAILURES.md` | Docs and video are not optional — protect this block, do not let build slip into it |

---

## Component tech stack (unchanged from before, compressed to what's actually built)

### 1. Pydantic schemas (`schemas.py`)

- `GraphState`: question, question_type, target_component, retrieved_chunks, evidence\[\], critique_flags\[\], confidence_score, retry_count, decision_brief, `pipeline_mode` (enum: `baseline`/`critic_off`/`critic_on`)
- `EvidenceRecord`: claim, citation (source, location), grounded (bool)
- `CritiqueFlag`: type (contradiction/uncited/gap), description, resolved (bool)
- `DecisionBrief`: answer, citations\[\], confidence_rationale, affected_components\[\] (nullable)
- **Stack:** `pydantic` v2

### 2. LangGraph skeleton (`graph.py`)

- Nodes: `input_guardrail → supervisor → research → retriever → evidence → critic → confidence_gate → (escalate | synthesis) → output_guardrail → memory_write`
- `pipeline_mode` selects the bypass: `baseline` skips Evidence/Critic/Gate (Retriever → single LLM answer); `critic_off` runs Evidence/Synthesis but skips Critic; `critic_on` is full path
- Guardrails: keep concrete and minimal — input guardrail rejects clearly off-topic questions; output guardrail blocks a brief shipping with zero citations
- **Stack:** `langgraph`, direct Anthropic/OpenAI SDK calls

### 3. Docker services

- Postgres (audit trail), Qdrant (2 collections: `docs`, `incidents`), Redis (present, minimally used)
- **Stack:** `docker-compose`

### 4. Ingestion (`ingest/`)

- Chunk docs/incidents by heading/section, embed with `text-embedding-3-small`, load to Qdrant with source+section metadata for citations
- **PII handling — state this explicitly in docs:** use synthetic or fully anonymized incident/ticket content only. No real names, emails, customer IDs, or internal usernames in source material. This is a one-line decision, not a build task, but it must appear in writing.
- **Stack:** `qdrant-client`, `openai`, plain Python chunkers

### 5. MCP servers

- Existing: GitHub MCP server on your target repo (live code reads, no RAG)
- Custom: dependency-graph server — offline `ast` walk of the repo → static graph (JSON or Postgres table) → MCP tool exposes `get_dependents()`/`get_callers()`
- **Stack:** `mcp` SDK, `ast` (stdlib)

### 6. Agent logic

- Research: query rewrite, no HyDE
- Retriever: Qdrant top-N, no reranker
- Evidence: LLM call mapping chunks → claims → citations, flags ungrounded claims
- Critic: LLM call for contradictions/gaps/uncited claims; simplified fixed-pattern version acceptable if time is short (see Day 2 table)
- Gate: heuristic score (citation coverage %, Critic-clean pass, retrieval score)
- Synthesis: LLM call producing `DecisionBrief`
- **Stack:** Anthropic/OpenAI structured output, validated against Pydantic

### 7. Audit trail (Postgres)

- Table: `investigations` (question, decision_brief JSON, confidence_score, pipeline_mode, resolved_flags JSON, token_usage, latency_ms, timestamp)
- **Stack:** `sqlalchemy` or `psycopg`

### 8. API + UI

- FastAPI: `POST /investigate`
- Streamlit: question box + brief output with citations. Nothing else.
- **Stack:** `fastapi`, `uvicorn`, `streamlit`

### 9. Comparative eval (Day 2 — the deliverable that most protects your grade)

- 3 demo questions + \~6–8 backing questions (including planted errors), each run through all 3 `pipeline_mode`s
- **Must-have metrics:** false-confidence rate, error-catch rate
- **Should-have (log for free, don't build extra scoring):** token cost and wall-clock latency per mode — this doubles as your System Design "trade-offs" evidence (e.g., "Critic-on: +Nx tokens, +Ys latency, catches N% more planted errors")
- **Error-handling cases (2–3):** malformed tool response / empty retrieval / MCP timeout — confirm the system escalates rather than crashing or fabricating an answer
- **Cut first if truly out of time:** Recall@K, citation-accuracy LLM-judge scoring, escalation-accuracy labeling — note their absence explicitly in docs rather than silently omitting them

---

## Rubric coverage checklist (confirm each has a home in your docs before submitting)

- [ ] Problem definition: scoping + clarity — one-pager, unchanged
- [ ] Data processing: sources — ingestion section
- [ ] Data processing: **PII handling** — explicit synthetic/anonymized-data statement
- [ ] Data processing: guardrails — input/output guardrail nodes, concretely described
- [ ] System design: architecture — LangGraph diagram + component list
- [ ] System design: **trade-offs** — dedicated section, at least 3 named trade-offs (agentic vs. RAG latency/cost, per-domain collections vs. flat index, retry cap vs. resolution completeness)
- [ ] Evals: task-specific — false-confidence rate, error-catch rate across 3 pipeline modes
- [ ] Evals: **error handling** — 2–3 broken-input test cases, graceful degradation confirmed
- [ ] Evals: **cost** — token usage per mode, logged and compared
- [ ] Evals: **latency** — wall-clock time per mode, logged and compared

## Learning objective coverage — two lists

**List 1 — built as part of the 2-day project (needed either for the graded system or the mandatory eval):**

- Chunking (heading/section-based)
- Data ingestion pipeline
- Vector embeddings
- Vector database (Qdrant, 2 collections)
- Multi-agent implementation via LangGraph (Supervisor/Research/Evidence/Critic/Gate/Synthesis)
- MCP: one open-source server (GitHub) + one custom-built server (dependency graph) + MCP client usage
- Evals: false-confidence rate, error-catch rate, cost, latency, across 3 pipeline modes
- Guardrails: input + output, 2 concrete rules each
- Basic memory/context: Redis session state + exact/keyword match against past investigations before re-running

**List 2 — deliberately deferred, do after Sep 27 submission, as standalone learning exercises rather than project features:**

- Indexer tuning / **ANN algorithm comparison** (HNSW vs. exact/brute-force in Qdrant, or vs. IVF in a second store like FAISS/pgvector)
- **Reranker** (cross-encoder rerank on top of vector search)
- **Query rewriting** as an explicit, isolated technique (not folded into a prompt) — compare rewritten vs. raw query retrieval quality
- **HyDE** — hypothetical-document embedding vs. plain query embedding, compared side by side
- **LLM-as-judge** as its own studied technique — build a small standalone judge harness (a few known-good/known-bad answer pairs, see if the judge scores them as expected) separate from using it inside the project eval
- **Semantic memory reuse** — embedding past Q&A pairs and retrieving by similarity, rather than exact/keyword match
- Richer guardrails (PII-detection input rule, more output validation rules)
- Second vector DB or IVF-based store, purely to compare against Qdrant/HNSW

Treat List 2 as a personal post-submission lab, not more capstone scope — each item there is small and isolated enough to build in an hour or two against your already-working Day-1/Day-2 system, without touching the graded deliverable.

## `FAILURES.md` — log every cut and pivot as it happens today and tomorrow, including scope cuts made under this compressed timeline (e.g., hardcoded dependency map instead of live AST if that's what happens) — these are legitimate failure-analysis content, not just things to hide.