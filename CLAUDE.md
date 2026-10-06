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
indexing/AST tooling has real code to operate on. It lives in its own
repository, `github.com/PrabuRepo/orderflow-app`, and is **never copied into
this repo** — the indexer reads it from GitHub (see "Knowledge domains"):
- `app/api.py` → `order_service.py` (the hub) → `payment_client.py` /
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
  source code cited from the code index (citation reads `repo@sha`), e.g.
  "Why were customers charged twice for one order (INC-1001), and is the
  cause confirmed?"
- **Impact Analysis** — code-dependency "blast radius" questions, answered
  deterministically from the AST server's real dependency graph, e.g. "What
  would be affected if we changed PaymentClient's retry logic?"

## Application profile (what makes the platform generic)

Everything specific to the application AppMind serves lives in one YAML file,
`config/apps/<id>.yaml` (here `orderflow.yaml`), loaded and validated by
`app_profile/` against `app_profile/appmind-app.schema.json` (unknown keys are
errors; secrets are env-var names only). It lists `sources.code` (repos),
`sources.docs` and `sources.incidents` (local folders), and optionally
`scope.description` (the off-topic guardrail's reference text) and
`scope.aliases` (component name → words that mean it, for questions that never
name the component). `APPMIND_APP` picks the profile; a single file is picked
automatically. Ingestion, the input guardrail, the supervisor and
`code_context.target_repo()` read it, and the agent prompts and UI intro
take the app's name and description from it (`app/prompts.py`); the indexer gets it as a generated
`indexer/targets.toml` (`python -m app_profile.export_targets`), never by import.
Thresholds and limits are code defaults, not config. Design:
`features/appmind-config/app-config-design.md`. **Do not hardcode OrderFlow
names in platform code** — add them to the profile.

## Knowledge domains

- **Code: a graph + source-file index, NOT RAG.** A deliberate architecture
  decision — code is never embedded into the vector store, because
  "what depends on X" is a graph question with one correct answer, and an
  embedded snapshot goes silently stale the moment the code changes. Code is
  **indexed ahead of time and read from AppMind's own store at question
  time**: answering a question never contacts GitHub or a local checkout.
  - **`indexer/`** — a **self-contained project** (own README, Dockerfile,
    requirements, tests; imports nothing from AppMind) that downloads each
    code repo in the application profile (exported to a generated `indexer/targets.toml`) at a pinned commit SHA, builds a static
    dependency/call graph (4-pass AST analysis), and writes the graph and
    source files to Postgres in one transaction per repo. It is built to move
    to its own repository later. Its only interface with AppMind is the data
    contract in `indexer/CONTRACT.md` (tables + graph JSON schema v1).
  - **`code_context/`** — AppMind's read-only view of that store: reads
    snapshots, checks `schema_version`, rebuilds the graph for queries. The
    only AppMind code that knows the contract. **Never import `indexer/`
    from AppMind or AppMind from `indexer/`** — `code_context/test_boundaries.py`
    fails the build if you do.
  - **Custom MCP server** (`mcp_servers/ast_server.py`) — exposes
    `list_components()` / `get_dependents()` / `get_callers()`; loads a
    snapshot file exported from Postgres, never parses code or reads a repo.
  - **GitHub MCP client** (`mcp_clients/github_client.py`) — kept as an
    optional live fallback; no longer on the default path.
  - Design and rationale: `features/code-index/code-index-design.md`.
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
| MCP SDK | Standard protocol for the code-graph tool (custom AST server) and the optional GitHub fallback client |
| Qdrant | Vector search — `docs` / `incidents` collections |
| PostgreSQL | Investigation audit trail (`memory/db.py`, one row per completed run) **and** the code knowledge store written by `indexer/` (`code_snapshots`, `code_files`, `code_heads`, `index_runs`) |
| Redis | Investigation-lookup cache (`memory/cache.py`), keyed on `(question, pipeline_mode)` |
| Streamlit | Single-page UI, calls the pipeline in-process — no separate API layer |
| OpenAI (`gpt-5.4-mini`) | LLM reasoning + embeddings (`text-embedding-3-small`) |
| Docker | Local infra — Postgres, Qdrant, Redis |

## Infra

- Docker: `docker compose up -d` from the repo root — Postgres, Qdrant,
  Redis. Use real connections, no in-memory/SQLite stand-ins. `docker compose
  up --build -d` also runs the app and a one-shot `indexer` (built from
  `./indexer` alone; refresh with `docker compose run --rm indexer`).
- Qdrant: `localhost:6333`, 2 collections (`docs`, `incidents`)
- Postgres: `localhost:5432` — `investigations` audit-trail table, written
  by `memory_write` on every run
- Redis: `localhost:6379` — investigation-lookup cache; `evals/run_eval.py`
  deliberately never reads it, so every eval run is measured fresh
- `.env` at the repo root (template: `setup-files/.env.example`) —
  `OPENAI_API_KEY`, `GITHUB_TOKEN` (a fine-grained, read-only PAT, used by the
  indexer), `GITHUB_TARGET_REPO` (also passed to the app as
  `APPMIND_CODE_REPO`, an optional override of which repo code questions are
  about; the default is the application profile's first code repo),
  Postgres/Qdrant/Redis connection settings. `APPMIND_EVAL_SNAPSHOT=<sha>`
  pins the eval harness's impact-analysis ground truth to an exact commit.

## Eval harness

Custom-built (`evals/run_eval.py` + `llm_as_judge/`), direct SDK calls —
not a framework like promptfoo/ragas. Runs all 9 dataset questions × 3
`pipeline_mode`s. Scoring: an LLM-as-judge for subjective questions, plus a
deterministic, zero-cost check for Impact Analysis questions (compares the
answer directly against the code graph's own `get_dependents()` output, from
a pinned snapshot).

## Safety/process notes

- Stay on default Claude Code permission mode. Do not enable
  bypassPermissions.
- Read diffs before approving. Confirm before running anything that
  touches paths outside this project folder.
- Commit to git after each working milestone.
- Don't print `.env` contents unnecessarily; it holds real API keys.
