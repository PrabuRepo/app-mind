# AppMind

**Application Knowledge & Decision Intelligence Agent** — an AI capstone project.

AppMind is an agentic, multi-domain investigation system for **one specific application**. It answers a question about that application — a business/functional question, an incident root-cause investigation, or a code-change impact analysis — by gathering evidence from documentation, incident reports, and the application's own source code, then producing an evidence-backed, auditable decision brief. A **Critic/Challenger agent** reviews that evidence for contradictions, uncited claims, and gaps before an answer is allowed to ship; if confidence stays low, AppMind escalates to a human rather than guess. The target application for this build is **OrderFlow**, a synthetic order-processing service purpose-built so the system has real code and real incidents to investigate without needing an external company's data.

Full documentation: [`docs/documentation.md`](docs/documentation.md) (problem statement, architecture, trade-offs, eval results, failure analysis) · [`docs/onepager.md`](docs/onepager.md) (the original approved design doc) · [`docs/architecture_high_level.md`](docs/architecture_high_level.md) and [`docs/detailed-flow-diagram.md`](docs/detailed-flow-diagram.md) (diagrams) · [`TASKS.md`](TASKS.md) (living build status) · [`FAILURES.md`](FAILURES.md) (pivots, cuts, and bugs, logged as they happened).

---

## Prerequisites

- **Python 3.11+** (built and tested on 3.13)
- **Docker Desktop** (Postgres, Qdrant, Redis run as containers — see `docker-compose.yml`)
- **An OpenAI API key** (LLM calls + embeddings)
- **A GitHub fine-grained personal access token**, scoped to **read-only "Contents"** access on your target repository only — used by the GitHub MCP integration to fetch real source text for incident investigations. Not the same as a classic token; generate it at github.com → Settings → Developer settings → Fine-grained tokens.
- **Node.js is *not* required.** An earlier plan used the official Filesystem MCP server (which needs Node); that was superseded by the GitHub MCP integration, which needs nothing installed locally (see [`docs/documentation.md`](docs/documentation.md) §4 for why).

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

# 4. Configure secrets
# Windows:
Copy-Item .env.example .env
# macOS/Linux:
cp .env.example .env
# then open .env and fill in OPENAI_API_KEY, GITHUB_TOKEN, GITHUB_TARGET_REPO

# 5. Load the knowledge base into Qdrant
python -m ingest.run_ingestion
```

## Running it

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
Results land in `evals/results/runs.jsonl` (every run, raw) and `evals/results/summary.md` (the summary tables).

**Test suites** (each module is runnable standalone):
```bash
python -m agents.test_evidence
python -m agents.test_critic
python -m mcp_servers.test_ast_server
python -m mcp_clients.test_github_client
python -m memory.test_db
python -m memory.test_cache
```

---

## Test Cases / Validation Steps

The Streamlit UI (`http://localhost:8501`) always runs in `critic_on` mode — the full investigation pipeline, including up to 2 Critic-triggered retries. Expect **10–25 seconds** per question; that's the real cost of the Critic, not a hang. Each question below is taken directly from the eval dataset (`evals/dataset.py`), so what you see in the UI matches what's actually measured — paste them in as-is.

### Use case 1 — Business/Functional ("how does this work")
> *Does OrderFlow reserve inventory before or after payment, and why does that ordering matter?*

**Look for:** an answer citing `architecture_overview.md`, and — this is the interesting part — whether it notices that `INC-1004_oversell_report.md` describes the *opposite* ordering under load. A good `critic_on` answer surfaces that contradiction rather than silently picking one source.

### Use case 2 — Incident/RCA ("why did this break")
> *Why were customers charged twice for one order (INC-1001), and is the cause confirmed?*

**Look for:** a citation from `app/payment_client.py` — real source code, fetched live via the GitHub MCP integration, not just the incident report. If it's working, you'll see the literal line about retries having no idempotency key, quoted verbatim. This is the single best question to demo the GitHub MCP payoff.

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

### Use case 7 — off-topic question (confidence gate, not a crash)
> *What is the capital of France?*

**Look for:** an honest escalation with zero citations, not a hallucinated answer and not an error page. Confirms empty retrieval correctly drives confidence to 0.0.

**If something looks wrong:** confirm all 3 containers are up (`docker compose ps`), confirm `.env` has real values (not the `.env.example` placeholders), and check the terminal running Streamlit for a printed `[node_name]` trace of what each pipeline step actually did — every node logs as it fires.

---

## Components

One line each, linking to the folder:

| Folder | What's in it |
|---|---|
| [`app/`](app/) | Core: Pydantic schemas, the LangGraph pipeline (`graph.py`), the retrieval coordinator, the LLM call wrapper, and the cache-aware entry point real callers use. |
| [`agents/`](agents/) | The Evidence agent (extracts and mechanically grounds cited claims) and the Critic agent (flags contradictions, uncited claims, and gaps) — the two LLM-driven reasoning steps the comparative eval is built around. |
| [`guardrails/`](guardrails/) | Input guardrail (blocks PII-looking questions before any cost is incurred) and output guardrail (blocks an uncited answer from shipping). |
| [`rag/`](rag/) | Embeds a question and searches Qdrant's `docs`/`incidents` collections — the RAG half of retrieval. |
| [`mcp_servers/`](mcp_servers/) | The custom AST dependency-graph MCP server — a local, offline static analysis of OrderFlow exposing `list_components`/`get_dependents`/`get_callers`. |
| [`mcp_clients/`](mcp_clients/) | The two MCP clients: a local stdio client for the AST server, and a remote client for GitHub's hosted MCP server (real source-text citations). |
| [`memory/`](memory/) | The Postgres audit trail (one row per investigation) and the Redis investigation-lookup cache. |
| [`ingest/`](ingest/) | Chunks, embeds, and loads the `knowledge-domains/` corpus into Qdrant. |
| [`knowledge-domains/`](knowledge-domains/) | The RAG corpus itself — OrderFlow's docs and incident reports, each incident planting a different kind of investigative trap. |
| [`orderflow-app/`](orderflow-app/) | OrderFlow — the synthetic target application AppMind investigates, including its one intentionally planted bug. |
| [`evals/`](evals/) | The comparative eval harness: the 9-question dataset, the runner, and the results. |
| [`llm_as_judge/`](llm_as_judge/) | The LLM-as-judge used by the eval harness to score subjective questions. |
| [`ui/`](ui/) | The Streamlit front end. |
| [`docs/`](docs/) | Submission documentation: the approved design doc, the full documentation, and both architecture diagrams. |
| [`setup-files/`](setup-files/) | Earlier setup notes — **stale**, written before the build diverged from the original plan (a different tech stack, different file layout). Use this README instead. |

---

## Project status

This is a capstone submission under active development up to the submission deadline. See [`TASKS.md`](TASKS.md) for exactly what's built and verified vs. still pending, and [`FAILURES.md`](FAILURES.md) for every pivot, cut, and bug along the way — logged as they happened, not reconstructed after the fact.
