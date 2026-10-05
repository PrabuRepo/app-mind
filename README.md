# AppMind

**Multi-agent AI platform that learns a team's applications and answers like an SME across product, engineering, and operations. Proof of concept on one app.** An AI Cohort capstone project (Application Knowledge & Decision Intelligence).

## Vision

Teams that own applications and services depend on knowledge scattered across business docs, architecture, source code, runbooks, and incident history, much of it held in the heads of a few experienced people. AppMind's vision is a platform that learns a team's applications and services and answers questions like a subject-matter expert (SME), from a **product**, **developer**, or **operations** perspective, with cited evidence and an honest "escalate to a human" when it isn't sure.

## What this build is

A **proof of concept on one specific application**. AppMind is an agentic, multi-domain investigation system that answers three kinds of question about that application, which roughly map to those perspectives:

- **Business/functional** (product): how does this work?
- **Incident root-cause** (operations): why did this break?
- **Code-change impact analysis** (developer): what would a change affect?

It gathers evidence from documentation, incident reports, and the application's own source code, then produces an evidence-backed, auditable decision brief. A **Critic/Challenger agent** reviews that evidence for contradictions, uncited claims, and gaps before an answer is allowed to ship; if confidence stays low, AppMind escalates to a human rather than guess.

The target application for this build is **OrderFlow**, a synthetic order-processing service purpose-built so the system has real code and real incidents to investigate without needing an external company's data. Extending the same pipeline to more applications, and tailoring answers to the asker's role, is the roadmap beyond this proof of concept, not something built today.

**Full documentation:**

- [`docs/detailed-design.md`](docs/detailed-design.md): problem statement, architecture, trade-offs, eval results, failure analysis
- [`docs/problem-definition-data-processing-evaluation.md`](docs/problem-definition-data-processing-evaluation.md): a focused 3-topic summary
- [`docs/high-level-design.md`](docs/high-level-design.md): the original approved design doc
- [`docs/detailed-flow-diagram.md`](docs/detailed-flow-diagram.md): the detailed pipeline diagram
- [`TASKS.md`](TASKS.md): living build status
- [`FAILURES.md`](FAILURES.md): pivots, cuts, and bugs, logged as they happened

---

## Components

One line each, linking to the folder:

| Folder | What's in it |
|---|---|
| [`app/`](app/) | Core: Pydantic schemas, the LangGraph pipeline (`graph.py`), the retrieval coordinator, the LLM call wrapper, and the cache-aware entry point real callers use. |
| [`agents/`](agents/) | The three LLM-driven reasoning agents the comparative eval is built around:<br>- **Evidence** — extracts claims with verbatim quotes, then mechanically verifies each quote against its source text (never trusted from the model).<br>- **Critic** — reviews evidence for contradictions, uncited claims, and gaps with a deliberately generic prompt; the sole difference between `critic_on` and `critic_off` is whether this agent runs.<br>- **Synthesis** — writes the final decision brief, from verified evidence (critic_off/critic_on) or raw retrieved chunks (baseline, unverified). |
| [`guardrails/`](guardrails/) | Input guardrail (blocks PII-looking questions before any cost is incurred) and output guardrail (blocks an uncited answer from shipping). |
| [`rag/`](rag/) | Embeds a question and searches Qdrant's `docs`/`incidents` collections — the RAG half of retrieval. |
| [`mcp_servers/`](mcp_servers/) | The custom AST dependency-graph MCP server. It loads a code snapshot (built ahead of time by the indexer) and exposes `list_components`/`get_dependents`/`get_callers`; it never parses code or touches a repository. |
| [`mcp_clients/`](mcp_clients/) | The AST client (a stdio client that points the AST server at the current code snapshot) and a GitHub MCP client, now an optional live fallback rather than part of the default path. |
| [`code_context/`](code_context/) | AppMind's read-only view of the code knowledge store: reads snapshots, checks their schema version, and rebuilds the dependency graph to answer questions. The only AppMind code that knows the indexer's data contract. |
| [`indexer/`](indexer/) | A **self-contained project** (own README, Dockerfile, requirements, tests) that turns configured GitHub repositories into the code knowledge store: dependency graph and source files in Postgres, tagged with the commit SHA. It imports nothing from AppMind; see [`indexer/CONTRACT.md`](indexer/CONTRACT.md). Built to move to its own repository. |
| [`memory/`](memory/) | The Postgres audit trail (one row per investigation) and the Redis investigation-lookup cache. |
| [`ingest/`](ingest/) | Chunks, embeds, and loads the `knowledge-domains/` corpus into Qdrant. |
| [`knowledge-domains/`](knowledge-domains/) | The RAG corpus itself — OrderFlow's docs and incident reports, each incident planting a different kind of investigative trap. |
| [`evals/`](evals/) | The comparative eval harness: the 9-question dataset, the runner, and the results. |
| [`llm_as_judge/`](llm_as_judge/) | The LLM-as-judge used by the eval harness to score subjective questions. |
| [`ui/`](ui/) | The Streamlit front end. |
| [`docs/`](docs/) | Submission documentation: the approved design doc, the full documentation, a focused 3-topic summary, and the detailed pipeline diagram. |
| [`features/`](features/) | Design documents for features beyond the submitted scope, e.g. [`code-index-design.md`](features/code-index-design.md) (the code knowledge index). |

**The target application.** AppMind investigates **OrderFlow**, a synthetic order-processing service that lives in its own repository, [`PrabuRepo/orderflow-app`](https://github.com/PrabuRepo/orderflow-app) (it includes one intentionally planted bug). It is **not** copied into this repository: the indexer reads it from GitHub and stores the derived knowledge.
| [`setup-files/`](setup-files/) | Earlier setup notes — **stale**, written before the build diverged from the original plan (a different tech stack, different file layout). Use this README instead. |

---

## Prerequisites

- **Python 3.11+** (built and tested on 3.13)
- **Docker Desktop** (Postgres, Qdrant, Redis run as containers — see `docker-compose.yml`)
- **An OpenAI API key** (LLM calls + embeddings)
- **A GitHub fine-grained personal access token**, scoped to **read-only "Contents"** access on your target repository only — used by the **indexer** to download the repository at a pinned commit. Not the same as a classic token; generate it at github.com → Settings → Developer settings → Fine-grained tokens. Answering a question never contacts GitHub.
- **Node.js is *not* required.** An earlier plan used the official Filesystem MCP server (which needs Node); that was superseded (see [`docs/detailed-design.md`](docs/detailed-design.md) §4 for why).

## Setup

```bash
# 1. Clone and enter the repo
git clone https://github.com/PrabuRepo/app-mind.git
cd app-mind

# 2. Create a virtual environment and install dependencies
python -m venv .venv
# Windows:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt

# 3. Start Postgres, Qdrant, Redis
docker compose up -d
docker compose ps          # all 3 should show "Up"

# 4. Configure secrets (template lives in setup-files/, .env itself goes at the repo root)
# Windows:
Copy-Item setup-files\.env.example .env
# macOS/Linux:
cp setup-files/.env.example .env
# then open .env and fill in OPENAI_API_KEY, GITHUB_TOKEN, GITHUB_TARGET_REPO

# 5. Load the docs/incidents knowledge base into Qdrant
python -m ingest.run_ingestion

# 6. Index the target repository's code (dependency graph + source files) into Postgres
pip install -r indexer/requirements.txt     # the indexer has its own requirements
cd indexer && python -m appmind_indexer.run && cd ..
```

The indexer reads the repositories listed in [`indexer/targets.toml`](indexer/targets.toml) from GitHub, pinned to a commit, and stores the result; re-running it skips repositories that haven't changed. Until it has run once, questions that need code (impact analysis, incident root cause) escalate with a clear "no code snapshot — run the indexer" message instead of guessing. See [`indexer/README.md`](indexer/README.md).

## Running it, fully containerized (one command)

A faster alternative to Setup steps 2, 3, 5 and 6 above — no local Python install, no manual venv, no manual ingestion or indexing. Still needs `.env` (Setup step 4), since secrets have to come from somewhere, and `.env` is passed into the container via `env_file:` in `docker-compose.yml` — never baked into the image itself.

**Start everything** — Postgres, Qdrant, Redis, the app itself, and a one-shot **indexer** container. On first boot, the app container automatically loads the docs/incidents knowledge base into Qdrant before starting the UI (checks whether `docs`/`incidents` already have data first, so a restart doesn't silently re-ingest every time), and the indexer indexes the target repository's code, then exits (the app does not wait on it):
```bash
docker compose up --build -d
```

**Check it's up:**
```bash
docker compose ps          # postgres, qdrant, redis, app should show "Up"; indexer runs once and exits (0)
```

**Refresh the code index** (e.g. after the target repository changes; an unchanged commit is skipped):
```bash
docker compose run --rm indexer
```

**Test it:** open `http://localhost:8501` — same UI, same behavior as running it locally.

**Watch it work** — every investigation's full `[input_guardrail]`/`[llm]`/`[mcp]`/`[trace]` logging (see `FAILURES.md`/`TASKS.md`'s observability work) streams live:
```bash
docker compose logs -f app
```

**Stop everything**, keeping all data (Postgres audit trail, Qdrant embeddings, Redis cache survive):
```bash
docker compose down
```

**Stop and wipe everything** — a genuinely clean slate; the next `up` re-runs ingestion from scratch:
```bash
docker compose down -v
```

**After changing source code**, rebuild just the app image — the other 3 containers don't need rebuilding:
```bash
docker compose up --build -d app
```

## Running it, locally (no Docker for the app itself)

Needs the `.venv` from Setup steps 2–5 above — use this path if you're actively modifying code (no image rebuild between runs) or want to run individual scripts/test suites directly.

**Streamlit UI** (single question box, cited answer, real-time investigation):
```bash
python -m streamlit run ui/streamlit_app.py
```
Opens at `http://localhost:8501`. Always runs in `critic_on` mode ("AppMind proper"). Must be launched with `python -m streamlit`, not the `streamlit` command directly — the project's `app/` package needs the working directory on `sys.path`, which only `-m` guarantees (see `FAILURES.md` #15).

**Graph smoke test** (all 3 `pipeline_mode`s end-to-end, no UI):
```bash
python -m app.graph
```

**Comparative eval harness** (the mandatory baseline vs. critic_off vs. critic_on evaluation):
```bash
python -m evals.run_eval                    # full 9-question x 3-mode run
python -m evals.run_eval --only D1,D2       # just these questions, for cheap iteration
python -m evals.run_eval --trials 2         # multiple trials per (question, mode)
```
Results land in `evals/results/runs.jsonl` (every run, raw) and `evals/results/summary.md` (the summary tables). Impact-analysis answers are scored against a code snapshot; pin it to an exact commit with `APPMIND_EVAL_SNAPSHOT=<sha>` so ground truth can't drift when the target repository changes (the summary records which snapshot was used).

**Test suites** (each module is runnable standalone):
```bash
python -m agents.test_evidence
python -m agents.test_critic
python -m mcp_servers.test_ast_server
python -m code_context.test_code_context     # needs the Postgres container
python -m code_context.test_boundaries       # guards the indexer / AppMind import boundary
python -m mcp_clients.test_github_client     # optional GitHub client; live, needs GITHUB_TOKEN
python -m memory.test_db
python -m memory.test_cache
cd indexer && python -m tests.run_all        # the indexer's own suite (also needs Postgres)
```

---

## Test Cases / Validation Steps

The Streamlit UI (`http://localhost:8501`) always runs in `critic_on` mode — the full investigation pipeline, including up to 2 Critic-triggered retries. Expect **10–25 seconds** per question; that's the real cost of the Critic, not a hang. Each question below is taken directly from the eval dataset (`evals/dataset.py`), so what you see in the UI matches what's actually measured — paste them in as-is.

### Use case 1 — Business/Functional ("how does this work")
> *Does OrderFlow reserve inventory before or after payment, and why does that ordering matter?*

**Look for:** an answer citing `architecture_overview.md`, and — this is the interesting part — whether it notices that `INC-1004_oversell_report.md` describes the *opposite* ordering under load. A good `critic_on` answer surfaces that contradiction rather than silently picking one source.

### Use case 2 — Incident/RCA ("why did this break")
> *Why were customers charged twice for one order (INC-1001), and is the cause confirmed?*

**Look for:** a citation from `app/payment_client.py` — real source code, read from the code index (the citation's source reads `PrabuRepo/orderflow-app@<commit>`, so you can see exactly which version of the code it came from), not just the incident report. If it's working, you'll see the bug described: each retry generates a new `transaction_id` with no idempotency key. This is the single best question to demo the code index payoff.

### Use case 3 — Impact Analysis ("what breaks if we change X")
> *What would be affected if we changed PaymentClient's retry logic?*

**Look for:** `OrderService` and `api` named as affected components — the deterministic, AST-verified answer (`mcp_servers/ast_server.py`'s `get_dependents()`), not a guess. This is the one answer you can check for correctness with certainty: it should match reality, not just sound plausible.

### Use case 4 — the false-alarm trap (tests the Critic doesn't over-react)
> *Orders for SKU-300 keep failing with insufficient stock errors. What bug is causing this?*

**Look for:** the answer should say this is **not a bug** — SKU-300 genuinely has zero stock, and the rejection is correct behavior (INC-1002). A weaker system confidently invents a defect here; watch for whether AppMind does too.

### Use case 5 — the hallucination-resistance check (tests the Critic doesn't invent things)
> *How does OrderFlow handle a customer requesting a refund?*

**Look for:** an honest "not covered by the documentation" answer, or an escalation — refunds are never mentioned anywhere in the corpus. A confident, specific answer here (inventing a refund policy) is a real failure, not a good sign.

### Use case 6 — input guardrail (PII blocking)
> *My email is jane.doe@example.com, can you refund my last order?*

**Look for:** an immediate escalation with no investigation — should return in well under a second. Confirms the PII regex check fires before any retrieval or LLM call runs (`guardrails/input_guardrail.py`).

### Use case 7 — off-topic question (input guardrail's topic-relevance check)
> *What is the capital of France?*

**Look for:** an immediate escalation, well under a second — not a hallucinated answer and not an error page. The question is embedded and compared against a reference description of OrderFlow's scope; below a measured similarity threshold, it's blocked at `input_guardrail` before any retrieval or LLM call (see `docs/detailed-design.md` §3's Components details). This *replaced* an earlier design where off-topic questions were only caught downstream via empty retrieval → confidence 0.0 — that path still exists as a fallback if the topic check's own embedding call fails.

**If something looks wrong:** confirm all containers are up — `docker compose ps` (4 if running fully containerized, 3 if running the app locally against Dockerized Postgres/Qdrant/Redis) — confirm `.env` has real values (not the `.env.example` placeholders), and check the logs for the `[trace]` line each investigation prints at the end, which shows exactly which nodes ran and which LLM calls fired. Locally, that's the terminal running Streamlit; containerized, it's `docker compose logs -f app`.


---

## Project status

This is a capstone project under active development. See [`TASKS.md`](TASKS.md) for exactly what's built and verified vs. still pending, and [`FAILURES.md`](FAILURES.md) for every pivot, cut, and bug along the way — logged as they happened, not reconstructed after the fact.
