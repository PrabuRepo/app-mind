# AppMind — Local Setup

Run these in order. Each step names what it's for and how to verify it worked before moving on.

**Note on commands below:** where Windows differs, it's shown as a separate **Windows (PowerShell)** block. On Windows 11, use `python` (not `python3` — Windows doesn't register that alias; see below).

## 1. Python 3.11+

**macOS/Linux:**
```bash
python3 --version        # confirm 3.11 or higher
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
python --version         # confirm 3.11 or higher — use `python`, not `python3`
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```
If `Activate.ps1` is blocked with an execution-policy error, run this once (in an admin PowerShell) and retry:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Verify (either OS, inside the activated venv): `python -c "import langgraph, qdrant_client, fastapi; print('ok')"` prints `ok`.

## 2. Docker Desktop + Docker Compose
Install Docker Desktop (docker.com). **On Windows 11, Docker Desktop requires the WSL2 backend** — the installer prompts for this; accept it, and install a Linux distro via `wsl --install` first if you don't already have one.
```powershell
docker --version
docker compose version
wsl --status              # Windows only — confirms WSL2 is the default
```
Both `docker` commands must print a version — if `docker compose` (space, not hyphen) fails, update Docker Desktop.

## 3. Start Postgres, Qdrant, Redis
Same command on both OSes:
```
docker compose up -d
docker compose ps
```
Verify each service — identical on Windows PowerShell and macOS/Linux since these run inside Docker's Linux containers:
```
curl http://localhost:6333/healthz            # Qdrant -> "healthz check passed"
docker exec -it appmind-redis redis-cli ping  # Redis -> "PONG"
docker exec -it appmind-postgres psql -U appmind -d appmind -c "\dt"   # Postgres -> empty table list, no error
```
(`curl` is built into Windows 11 by default — no separate install needed.)

## 4. API keys
- OpenAI: platform.openai.com → API keys → create new key
- Anthropic: console.anthropic.com → API keys → create new key
- GitHub: github.com/settings/tokens → generate a fine-grained token with **read-only repo access** to your target application's repo

## 5. Configure secrets

**macOS/Linux:**
```bash
cp .env.example .env
```
**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```
Open `.env` in any text editor and paste in the 3 keys above plus your target repo (`owner/repo-name`). Confirm `.env` is listed in `.gitignore` before you touch git.

## 6. Clone your target application repo locally
Identical on both OSes:
```
git clone https://github.com/<owner>/<repo-name>.git ./target-app
```
This local checkout is what the custom MCP server's AST walk reads to build the dependency graph — it does not need to be inside your AppMind repo, just reachable by path.

## 7. Run the GitHub MCP server

**macOS/Linux:**
```bash
docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN=$GITHUB_TOKEN ghcr.io/github/github-mcp-server
```
**Windows (PowerShell):**
```powershell
docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN=$env:GITHUB_TOKEN ghcr.io/github/github-mcp-server
```
(Note the `$env:` prefix — PowerShell's syntax for reading an environment variable, vs. bash's plain `$VAR`. Exact invocation may differ slightly by MCP server version — check the server's own README if this doesn't start cleanly.)

## 8. Run your custom dependency-graph MCP server
Once you've written it (Day 1 PM in the implementation plan) — same command both OSes:
```
python mcp_servers/dependency_graph_server.py
```

## 9. Run the FastAPI backend
Same command both OSes:
```
uvicorn app.main:app --reload --port 8000
```
Verify: `curl http://localhost:8000/docs` returns the Swagger UI HTML.

## 10. Run the Streamlit UI
Same command both OSes:
```
streamlit run ui/app.py
```
Opens at `http://localhost:8501`.

## Port conflict check (run this first if anything above fails to bind)

**macOS/Linux:**
```bash
lsof -i :5432 -i :6333 -i :6379 -i :8000 -i :8501
```
**Windows (PowerShell):**
```powershell
Get-NetTCPConnection -LocalPort 5432,6333,6379,8000,8501 -ErrorAction SilentlyContinue |
    Select-Object LocalPort, OwningProcess
```
If something else already owns one of these ports, either stop it or change the port mapping in `docker-compose.yml` / the `uvicorn`/`streamlit` command. A common Windows conflict: a locally installed Postgres service auto-starting on 5432 — check `services.msc` for a running "postgresql" service if so.



## Components
Here's the full component inventory, organized by category — this is everything in your 2-day build:

RAG pipeline (docs + incidents only)

Chunker (heading/section-based) for the 7 markdown files
Embedding generation (OpenAI text-embedding-3-small)
Vector database (Qdrant, 2 collections: docs, incidents)
Retriever (top-N similarity search per collection)
(No reranker, no HyDE, no query-rewrite-as-distinct-step — those are your List 2 stretch items)

Agent / Orchestration (LangGraph, multi-agent)

Supervisor Agent — routes question to domain
Research Agent — decides RAG vs. MCP/AST path, issues queries/tool calls
Evidence Agent — maps retrieved chunks/tool results to cited claims
Critic Agent — checks evidence for contradictions/gaps/uncited claims (this is the component your comparative eval is built around)
Confidence Gate — heuristic scoring, routes to escalation or synthesis
Synthesis Agent — produces the final DecisionBrief
pipeline_mode flag — three bypass configurations on this one graph (baseline / critic_off / critic_on)

MCP (code domain, no RAG)

Filesystem MCP server (existing/official) — live reads of orderflow-app/
Custom dependency-graph MCP server — offline AST walk, exposes get_dependents()/get_callers()
MCP client usage inside the Research Agent

Guardrails

Input guardrail node — rejects off-topic questions (+ a PII-looking-input rule, per our earlier addition)
Output guardrail node — blocks a brief from shipping with zero citations (+ blocks shipping with unresolved critique flags)

Memory / Context management

Redis — session state for the running GraphState
Postgres investigations table — persisted audit trail, also queried for a simple exact/keyword-match "have we seen this before" lookup before running a fresh investigation

Evals

Eval harness script — runs demo + backing questions through all 3 pipeline_modes
Metrics: false-confidence rate, error-catch rate (must-have), citation accuracy via LLM-as-judge (should-have), cost (token usage) and latency (wall-clock) per mode
Error-handling test cases — 2–3 broken-input scenarios (dead MCP call, empty retrieval)
LLM-as-judge — used both inside the eval harness and as its own studied technique

Infra / API / UI

Pydantic schemas (GraphState, EvidenceRecord, CritiqueFlag, DecisionBrief)
Docker services: Postgres, Qdrant, Redis
FastAPI backend (POST /investigate)
Streamlit UI (question box + brief output, no polish)


## Code Executions

How to run it yourself, to see the same thing:
$env:PYTHONPATH = "."
python app/schemas.py    # sanity-checks the schemas + shows Pydantic validation catching a bad input
python app/graph.py      # runs all 3 pipeline_modes end-to-end, prints each node as it fires


python -m ingest.run_ingestion
python -m ingest.test_retrieval

