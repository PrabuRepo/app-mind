# AppMind — Project Context for Claude Code

Read this file at the start of every session. It describes what this
project currently is — architecture, tech stack, functionality — not a
build plan. For history (why things changed shape) see `FAILURES.md`; for
live build status see `TASKS.md`.

## What this project is

AppMind: an agentic, multi-domain "Application Knowledge & Decision
Intelligence Agent" that investigates questions about one specific
application, produces evidence-backed decision briefs, and escalates to a
human when confidence is low. Core differentiator: a Critic/Challenger agent
that catches contradictions and false confidence — this is what the
mandatory comparative eval measures.

## Target application: "OrderFlow" (synthetic, intentionally)

A small order-processing service, purpose-built for this project so
ingestion/AST tooling has real code to operate on. Hosted at
`github.com/PrabuRepo/orderflow-app`, checked out locally at
`orderflow-app/app/`:
- `api.py` → `order_service.py` (the hub) → `payment_client.py` /
  `inventory_client.py` / `notification_service.py`
- **Planted bug (intentional — do not "fix" without checking eval impact
  first):** `payment_client.py`'s retry loop generates a new transaction on
  every retry with no idempotency key, causing duplicate charges. Subject of
  INC-1001 and the Incident/RCA demo question.

## Use cases (the 3 supported question types)

- **Business/Functional** — "how does this work" questions, answered from
  docs + incidents, e.g. "Does OrderFlow reserve inventory before or after
  payment, and why does that ordering matter?"
- **Incident/RCA** — root-cause investigation of a real incident, with real
  source code cited via GitHub MCP, e.g. "Why were customers charged twice
  for one order (INC-1001), and is the cause confirmed?"
- **Impact Analysis** — code-dependency "blast radius" questions, answered
  deterministically from the AST server's real dependency graph, e.g. "What
  would be affected if we changed PaymentClient's retry logic?"

## Knowledge domains

- **Code: MCP/AST search only. NOT RAG.** A deliberate architecture
  decision — code is never embedded into the vector store, because
  cross-file dependency analysis needs every file parsed together (not
  fetched one-at-a-time), and an embedded snapshot goes silently stale the
  moment the code changes.
  - **Custom MCP server** (`mcp_servers/ast_server.py`) — local, offline
    4-pass static analysis exposing `list_components()` / `get_dependents()`
    / `get_callers()`. Needs a local checkout of the target app.
  - **GitHub MCP** (`mcp_clients/github_client.py`) — the official, remote
    GitHub MCP server, fetching real file text on demand for citation-grade
    evidence on Incident/RCA questions. PAT-scoped read-only.
- **RAG domains: `docs` + `incidents` only** (2 Qdrant collections, kept
  separate so each has its own top-k policy per question type). Source
  files in `knowledge-domains/docs/` (3 files) and `knowledge-domains/incidents/`
  (4 files). Each incident plants a DIFFERENT kind of problem:
  - `INC-1001`: real, code-verifiable bug (the payment retry issue above)
  - `INC-1002`: a false alarm — looks like a bug, is actually correct
    behavior — tests whether the Critic confidently misdiagnoses it
  - `INC-1004`: a documentation contradiction, independent of code — a
    postmortem claims payment happens before inventory reservation,
    contradicting `architecture_overview.md`'s stated design rule
  - `INC-1003`: mundane filler, not a trap

## Architecture (LangGraph, one graph, three modes)

```
input_guardrail → supervisor → research → retriever → evidence → critic
  → confidence_gate → (escalate | synthesis) → output_guardrail → memory_write
```

`pipeline_mode` is the single flag driving the mandatory comparative eval —
one graph, not three separate systems:
- `baseline`: retrieve → answer directly, skips evidence/critic/gate
- `critic_off`: full path minus the critic node
- `critic_on`: full path, including critic (this is "AppMind" proper)

Retry loop: Critic → Research, capped at `retry_count < 2`.

Guardrails are real, not placeholders: input blocks PII-shaped questions
(email/phone/SSN) before any retrieval or LLM cost; output blocks an
uncited answer from shipping as a confident response.

Schemas in `app/schemas.py`: `GraphState`, `EvidenceRecord`, `CritiqueFlag`,
`DecisionBrief`, `PipelineMode`. Graph in `app/graph.py` — every node has
real logic, verified end-to-end for all 3 `pipeline_mode`s (`python -m
app.graph` runs a live smoke test).

## Tech stack

| Framework | Role |
|---|---|
| LangGraph | Stateful orchestration — conditional routing per `pipeline_mode`, the Critic retry loop |
| Pydantic | Validated schemas for every inter-node payload |
| MCP SDK | Standard protocol for both code-access tools (AST server + GitHub) |
| Qdrant | Vector search — `docs` / `incidents` collections |
| PostgreSQL | Investigation audit trail (`memory/db.py`) — one row per completed run |
| Redis | Investigation-lookup cache (`memory/cache.py`), keyed on `(question, pipeline_mode)` |
| Streamlit | Single-page UI, calls the pipeline in-process — no separate API layer |
| OpenAI (`gpt-5.4-mini`) | LLM reasoning + embeddings (`text-embedding-3-small`) |
| Docker | Local infra — Postgres, Qdrant, Redis |

## Infra

- Docker: `docker compose up -d` from the repo root — Postgres, Qdrant,
  Redis. Use real connections, no in-memory/SQLite stand-ins.
- Qdrant: `localhost:6333`, 2 collections (`docs`, `incidents`)
- Postgres: `localhost:5432` — `investigations` audit-trail table, written
  by `memory_write` on every run
- Redis: `localhost:6379` — investigation-lookup cache; `evals/run_eval.py`
  deliberately never reads it, so every eval run is measured fresh
- `.env` at the repo root (template: `setup-files/.env.example`) —
  `OPENAI_API_KEY`, `GITHUB_TOKEN` (a fine-grained, read-only PAT),
  `GITHUB_TARGET_REPO`, Postgres/Qdrant/Redis connection settings

## Eval harness

Custom-built (`evals/run_eval.py` + `llm_as_judge/`), direct SDK calls —
not a framework like promptfoo/ragas. Runs all 9 dataset questions × 3
`pipeline_mode`s. Scoring: an LLM-as-judge for subjective questions, plus a
deterministic, zero-cost check for Impact Analysis questions (compares the
answer directly against the AST server's own `get_dependents()` output).

## Safety/process notes

- Stay on default Claude Code permission mode. Do not enable
  bypassPermissions.
- Read diffs before approving. Confirm before running anything that
  touches paths outside this project folder.
- Commit to git after each working milestone.
- Don't print `.env` contents unnecessarily; it holds real API keys.
