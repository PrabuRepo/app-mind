# AppMind — Project Context for Claude Code

Read this file at the start of every session. It captures decisions made
across an earlier planning conversation — do not relitigate them without
flagging it to the user first.

## What this project is

AppMind: an AI capstone project. An agentic, multi-domain "Application
Knowledge & Decision Intelligence Agent" that investigates questions about
one specific application, produces evidence-backed decision briefs, and
escalates to a human when confidence is low. Core differentiator: a
Critic/Challenger agent that catches contradictions and false confidence —
this is what the mandatory comparative eval measures.

**Deadline: submission is due EOD tomorrow.** Time is genuinely tight.
Prioritize a working end-to-end system over completeness. When in doubt,
follow the cut-first order in the "What to cut if behind" section below.

## Target application: "OrderFlow" (synthetic, intentionally)

A small order-processing service, purpose-built for this capstone so
ingestion/AST tooling has real code to operate on without needing an
external repo. Located in `orderflow-app/app/`:
- `api.py` → `order_service.py` (the hub) → `payment_client.py` /
  `inventory_client.py` / `notification_service.py`
- **Planted bug (intentional, do not "fix" without checking eval impact
  first):** `payment_client.py`'s retry loop generates a new transaction on
  every retry with no idempotency key — causes duplicate charges. This is
  the subject of INC-1001 and the Incident/RCA demo question.

## Knowledge domains

- **Code: MCP/AST search only. NOT RAG.** This was a deliberate,
  extensively-discussed architecture decision — do not add code to the
  vector store. Existing MCP server = official **Filesystem MCP server**
  (not GitHub — there's no real hosted repo), pointed at `orderflow-app/`.
  Custom MCP server = offline AST walk exposing `get_dependents()` /
  `get_callers()`.
- **RAG domains: `docs` + `incidents` only** (2 collections, not 3 —
  "tickets" was cut entirely to save time). Source files already written,
  in `knowledge-domains/docs/` (3 files) and `knowledge-domains/incidents/`
  (4 files). Each incident plants a DIFFERENT kind of problem:
  - `INC-1001`: real, code-verifiable bug (the payment retry issue above)
  - `INC-1002`: a false alarm — looks like a bug, is actually correct
    behavior — tests whether the Critic (or a baseline without one)
    confidently misdiagnoses it
  - `INC-1004`: a documentation contradiction, independent of code — a
    postmortem claims payment happens before inventory reservation,
    contradicting `architecture_overview.md`'s stated design rule
  - `INC-1003`: mundane filler, not a trap

## Architecture (LangGraph, one graph, three modes)

`input_guardrail → supervisor → research → retriever → evidence → critic
→ confidence_gate → (escalate | synthesis) → output_guardrail →
memory_write`

**`pipeline_mode` is the single flag driving the mandatory comparative
eval** — do not build separate systems for this:
- `baseline`: retrieve → answer directly, skips evidence/critic/gate
- `critic_off`: full path minus the critic node
- `critic_on`: full path, including critic (this is "AppMind" proper)

Retry loop: Critic → Research, capped at `retry_count < 2`.

Schemas already defined in `app/schemas.py`: `GraphState`, `EvidenceRecord`,
`CritiqueFlag`, `DecisionBrief`, `PipelineMode`. Graph skeleton in
`app/graph.py` — all nodes currently STUBBED but verified working end to
end for all 3 pipeline_modes (run `python -m app.graph` to confirm).

## Infra (already running — use directly, no need to stand up or defer)

- **Docker confirmed working.** Postgres, Qdrant, Redis all running via
  `docker-compose.yml`. Use real connections now, not in-memory/SQLite
  stand-ins — that hedge was for before Docker was confirmed working and
  no longer applies.
- Qdrant: `localhost:6333`, 2 collections (`docs`, `incidents`)
- Postgres: `localhost:5432`, intended for an `investigations` audit-trail
  table (not yet created)
- Redis: `localhost:6379`, intended for session state (not yet wired up)
- `.env` has real `OPENAI_API_KEY` (works for `gpt-5.4-mini`,
  `gpt-5.4-nano`, `text-embedding-3-small`) — model choice between mini/nano
  for agent LLM calls not yet decided, pick based on cost/latency once the
  eval harness exists to measure it.

## What's already built and verified working

- `app/schemas.py` — all Pydantic schemas, runs cleanly
- `app/graph.py` — LangGraph skeleton, all 3 pipeline_modes tested working
- `ingest/chunker.py` — heading-based markdown chunker, tested against real
  files
- `ingest/run_ingestion.py` — full pipeline, embeds via OpenAI, loads into
  real Qdrant
- `ingest/test_retrieval.py` — sanity-check retrieval script
- `orderflow-app/` — the synthetic app, all files valid Python/AST
- `knowledge-domains/` — all 7 docs/incidents files

## What's NOT built yet (in priority order)

1. Filesystem MCP server + custom AST dependency-graph MCP server
2. Real `research`/`retriever` logic in `graph.py` (currently returns fake
   data) — should call real Qdrant search + MCP tools
3. Real `evidence` and `critic` logic (currently stubs)
4. Postgres `investigations` table + audit trail writes
5. Redis session state wiring
6. Eval harness: 3 demo questions (one per type: Business/Functional,
   Incident/RCA, Impact Analysis) + ~6–8 backing questions, run through all
   3 pipeline_modes. Metrics, in priority order:
   - Must-have: false-confidence rate, error-catch rate
   - Should-have: citation accuracy (LLM-as-judge), cost/latency per mode
     (log token usage + wall-clock time — cheap to add, don't skip)
   - Nice-to-have, cut first: Recall@K, escalation accuracy
   - Also needed: 2–3 deliberate error-handling test cases (dead MCP call,
     empty retrieval) confirming graceful escalation, not a crash
7. Streamlit UI — single page, question box, brief output with citations,
   nothing else
8. Docs (4–5 pages) — must explicitly include: a PII statement (data is
   synthetic/anonymized, state this plainly), a dedicated Trade-offs
   section (at least 3 named trade-offs — agentic latency/cost vs. RAG,
   per-domain collections vs. flat index, retry cap vs. resolution
   completeness), and the cost/latency/error-catch/false-confidence tables
   from the eval
9. Demo video (3 min) covering the 3 demo questions
10. `FAILURES.md` — log pivots/cuts as they happen, not reconstructed later

## What to cut first if time runs short (in this order)

1. Streamlit polish (bare functional UI is fine)
2. Recall@K, escalation-accuracy metrics (state their absence in docs
   rather than silently omitting)
3. Backing eval set size (6–8 down to 4 if truly desperate)
4. If the custom AST MCP server slips: hardcode a small dependency map for
   `OrderService` as a stopgap, note it as a known limitation in
   `FAILURES.md` — do not lose the whole Impact Analysis demo question

**Never cut:** the Critic on/off/baseline eval itself, the audit trail, the
PII statement, the Trade-offs section, `FAILURES.md`.

## Explicitly deferred to AFTER submission (do not build now)

Reranker, HyDE, query-rewrite-as-a-distinct-step, ANN algorithm comparison
(HNSW vs. exact/IVF), semantic memory reuse (embedding-based), richer
guardrails beyond the 2 basic input/output rules already planned, a second
vector DB. These were deliberately scoped out of the 2-day build — do not
suggest adding them back in under time pressure.

## Safety/process notes

- Stay on default Claude Code permission mode. Do not enable
  bypassPermissions.
- Read diffs before approving. Confirm before running anything that
  touches paths outside this project folder.
- Commit to git after each working milestone (schemas, graph skeleton,
  each MCP server, each real node's logic) — not just at the end.
- Don't print `.env` contents unnecessarily; it holds real API keys.
