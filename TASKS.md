# TASKS.md — living status tracker

Updated as work happens (unlike CLAUDE.md/impl-plan.md, which are the fixed
plan). Statuses: **Complete** / **Pending** / **Paused** / **Superseded** /
**TODO (later)**. See [FAILURES.md](FAILURES.md) for *why* things changed
shape; this file is only *what state each piece is in*.

## Core pipeline (CLAUDE.md priority order)

| # | Item | Status | Note |
|---|---|---|---|
| — | Docker (Postgres, Qdrant, Redis) | Complete | all 3 containers confirmed running |
| — | `app/schemas.py` | Complete | extended this session: `RetrievedChunk`, `ResearchPlan`, `agent_errors`, `llm_calls`, quote/resolution fields |
| — | LangGraph skeleton (`app/graph.py`) | Complete | shape + `pipeline_mode` routing verified for all 3 modes |
| — | Ingestion (`ingest/`) | Complete | ran; fixed a Windows cp1252 encoding bug and a `qdrant-client` API change along the way |
| 1a | Custom AST dependency-graph MCP server | Complete | `mcp_servers/ast_server.py` + `mcp_clients/ast_client.py`; 14/14 tests passing |
| 1b | Filesystem MCP server | **Superseded** | needs Node.js, still not installed on this machine (re-verified 2026-09-27) — but this row is no longer just "paused waiting to resume": the underlying goal (real code text, not just AST structure) is now met by the GitHub MCP integration instead (see Housekeeping row below + Decisions log's "Reviving GitHub MCP" entry). Not expected to get built unless the target app ever lacks a real hosted repo again |
| 2 | Real `research`/`retriever` logic | Complete | `app/retrieval.py` + `rag/search.py`; baseline now actually retrieves (was a strawman before) |
| 3 | Real `evidence`/`critic` logic | Complete | `agents/evidence.py` + `agents/critic.py`; grounding checked in code, not trusted; flags are sticky across retries |
| 4 | Postgres `investigations` audit trail | Complete | `memory/db.py`; idempotent `CREATE TABLE IF NOT EXISTS`, one row per completed investigation, written from `memory_write`. Never raises — a dead Postgres degrades to a printed warning, not a crash. Verified against the real local container, not mocked (per CLAUDE.md) |
| 5 | Redis investigation-lookup cache | Complete | `memory/cache.py` + `app/investigate.py`; keyed on (normalized question, pipeline_mode) — mode is part of the key on purpose, see Decisions log. `evals/run_eval.py` deliberately never goes through this path (would corrupt the comparative eval's cost/latency numbers). `ui/streamlit_app.py` now calls `app.investigate.investigate()` instead of invoking the graph directly |
| 6a | Real `synthesis` logic (Step 0, discovered blocking #6) | Complete | `agents/synthesis.py`; was still the original stub — no eval metric can read answer *content* without this; baseline now genuinely answers + cites (unverified, `grounded=False`), critic_off/critic_on cite only verified evidence |
| 6b | Eval harness (`evals/`) | Complete | `evals/dataset.py` (9 questions), `llm_as_judge/judge.py`, `evals/run_eval.py`; ran the full set — results in `evals/results/runs.jsonl` + `summary.md`. See Decisions log for headline numbers and real findings |
| 7 | Streamlit UI | Complete (V1) | `ui/streamlit_app.py`; verified end-to-end in the browser (real question -> real escalation -> real citations rendered). Only imports `app.graph`/`app.schemas` — no direct dependency on `agents/`/`rag/`/`mcp_clients/`, same boundary `evals/run_eval.py` uses. V2 fast-follow (not built): pipeline_mode selector, critique-flag display, retrieval/agent-error display, cost/latency footer — deliberately deferred per user's "start simple" steer |
| 8 | Docs (4–5 pages) | Pending | blocked on #6 for the actual numbers; PII statement + Trade-offs section are "never cut" |
| 9 | Demo video (3 min) | Pending | blocked on #6 and #7 |
| 10 | `FAILURES.md` | Ongoing | actively maintained, 12 entries so far |

## Housekeeping

| Item | Status | Note |
|---|---|---|
| Full reorg (`guardrails/`, `agents/`, `rag/`, `mcp_clients/`, `memory/`, `llm_as_judge/`, `evals/`) | Complete | all test suites re-verified passing after the move |
| `orderflow-app/` moved to `app/` layout | Complete | matches CLAUDE.md's expected path |
| git — `orderflow-app/` | Complete | you've committed this to its own GitHub repo |
| git — `ai-capstone/` (the rest: `app/`, `agents/`, `ingest/`, etc.) | Paused | no repo initialized yet; you're managing commits manually |
| `llm_as_judge/` real implementation | Complete | stale note fixed 2026-09-27 — this was marked TODO from before #6 was built, but `llm_as_judge/judge.py` has been real and in active use since the eval harness was built, including the two re-runs this session |
| "One command to run everything" script (`run.ps1` or a README section) | TODO (later) | `docker-compose up -d` + `python -m streamlit run ui/streamlit_app.py`. Decided NOT to dockerize the UI/app tier (discussed in chat 2026-09-27): app code changes too often during active development to be worth containerizing, isn't in CLAUDE.md's scope, and none of Postgres/Redis/docs/video is done yet. This script gets the same one-command convenience without any of that cost — revisit once the core build is further along |
| GitHub MCP code-read integration (`mcp_clients/github_client.py`) | Complete | Remote hosted server + scoped read-only PAT, wired into `app/retrieval.py` for `incident_rca` questions only. Verified end-to-end through the real graph for the actual INC-1001 demo question: `critic_on` cites real `payment_client.py` text (grounded=True), including the literal "no idempotency key sent to the gateway" line — the concrete payoff this was built for. 11/11 checks passing in `mcp_clients/test_github_client.py` against the real remote server. No changes needed to `agents/evidence.py`'s grounding CODE — `is_grounded()` was already source-agnostic; only added one line to its LLM instructions about quoting raw source code. See Decisions log for two real gotchas found along the way |
| Local Docker GitHub MCP server (`ghcr.io/github/github-mcp-server`) | **Deferred, explore later** | User wants to explore this path later (self-hosted, `--read-only`/`GITHUB_TOOLSETS` server-level tool restriction, no dependency on GitHub's remote endpoint) as a follow-up/comparison once the remote path is working — not abandoned, just sequenced after |

## Decisions log

### 2026-09-27 — Build order: eval harness (#6) before Postgres (#4) / Redis (#5)
CLAUDE.md's numbered list happens to put the Postgres audit trail before the
eval harness, but that's just the order it was written down in, not a real
dependency — the eval harness computes every required metric (false-confidence
rate, error-catch rate, citation accuracy, cost/latency) straight from
`build_graph().invoke()`'s return value in Python, and can write its own
results to a local file in `evals/`. It needs neither Postgres nor Redis.

Building the harness first also means Postgres gets wired up at the moment
~30 real investigations (3 demo + backing questions x 3 pipeline_modes) are
actually flowing through the graph, so the table starts populated with real
data instead of sitting empty until something exercises it. Postgres/Redis
remain "never cut" per CLAUDE.md — this changes *when* they get built, not
*whether*. Both are cheap (one table + one insert; one cache read/write), so
reordering carries little risk.

Agreed with the user in chat; not a silent deviation.

### 2026-09-27 — Eval framework: direct SDK calls, not promptfoo/ragas/deepeval/LangSmith
Compared all four against a custom harness. Rejected because each is built
around a generic metric shape (prompt-in/output-out, RAG faithfulness,
pytest-style hallucination scoring) while this project's actual deliverable
is bespoke metrics CLAUDE.md itself defines: false-confidence rate, error-
catch rate against 4 named planted traps, and a deterministic AST-verified
check for Impact Analysis — none of which map onto a framework's built-in
assertions. Would've meant writing the same custom judge logic anyway, wrapped
in a new dependency (and for LangSmith, a new account/API key) this close to
a deadline. `agents/evidence.py`/`agents/critic.py` already establish the
exact pattern needed (`structured_call` + a Pydantic schema) — the judge in
`llm_as_judge/` is just one more instance of that, zero new plumbing.
Matches CLAUDE.md's stated stack ("direct Anthropic/OpenAI SDK calls").

### 2026-09-27 — Minimum LLM calls: 1 trial per (question, mode), not 3; 9 questions, not 11
Originally proposed 3 trials for the 3 demo questions (to get a stable rate
given the variance FAILURES.md #11 found) and 1 for backing questions: 51
total runs across 11 questions. User asked to minimize LLM calls for this
capstone pass instead. Changed to 1 trial everywhere, and cut the dataset to
9 questions (dropped a planned ambiguous-Impact-Analysis edge case — see
evals/dataset.py's module docstring): `9 questions x 3 modes x 1 = 27 runs`.
All 3 required demo types and all 4 originally-planted-plus-constructed traps
are still fully covered. Trade-off: a single run of D1/D2 won't re-surface
variance the way 3 trials would; stated plainly where it showed up (see next
entry), not averaged away — add trials later via `--trials N` if more
coverage is needed.

### 2026-09-27 — Eval harness built and run; headline numbers (1 trial, treat as directional)
`agents/synthesis.py` (Step 0 — was still the original answer-stub, blocked
every content-reading metric below), `llm_as_judge/judge.py`, `evals/dataset.py`
(9 questions: D1-D3 + B1-B6), `evals/run_eval.py`. Full run: 27 graph runs +
4 reused error-handling cases (4/4 passing, zero duplicate LLM cost — see the
`run_error_handling_cases()` extraction in `app/test_research_retriever.py`).

| Metric | baseline | critic_off | critic_on |
|---|---|---|---|
| False-confidence rate | 0.286 | 0.429 | **0.143** |
| Error-catch rate (planted traps) | 0.5 | 0.5 | **0.75** |
| Citation accuracy (LLM judge) | 0.739 | 0.92 | 0.79 |
| Escalation rate | 0.0 | 0.0 | 0.444 |
| Mean tokens / mean latency | 1033 / 2.2s | 2147 / 3.6s | 8243 / 11.3s |

Headline: critic_on has the lowest false-confidence rate and the highest
error-catch rate of the three — the direction the whole project is staked
on — at a real, measured cost (~8x tokens, ~5x latency vs. baseline). This is
now a number from 27 runs, not the single anecdote in FAILURES.md #11.

**Caveats to carry into the docs, not smooth over:**
- 1 trial per question — these numbers are directional, not final. Re-run
  with `--trials N` before they go in the submission if time allows.
- D1 (the doc-vs-doc contradiction) triggered false confidence in **all
  three modes**, including critic_on, in this run — same variance pattern as
  FAILURES.md #11, not a new bug.
- D3 (Impact Analysis): critic_on escalated instead of answering, because
  the Critic judged the AST dependency data insufficient even though
  baseline/critic_off answered it with perfect component recall. This is the
  opposite failure mode from false confidence — over-caution costing a
  correct, available answer. Worth a line in the docs' Trade-offs section
  ("retry cap vs. resolution completeness" already anticipates this kind of
  trade-off).
- B5 (refund hallucination check): baseline and critic_off both fabricated a
  refund mechanism the corpus never documents; critic_on did not — the
  clearest single data point in favor of the Critic in this run.
- No judge_error or agent_errors occurred in any of the 27 runs.
- `DecisionBrief.affected_components` only ever echoes `target_component`
  (the thing asked about), not its actual dependents — the Impact Analysis
  ground-truth check works around this by checking the AST graph directly
  against the answer TEXT rather than that field. Noted, not fixed — low
  priority, doesn't block anything.

### 2026-09-27 — Postgres/Redis wiring: external cache wrapper, raw psycopg, 24h TTL
Three design forks, decided with the user before building:
1. **Cache lookup as an external wrapper (`app/investigate.py`), not a new graph
   node.** `app/graph.py`'s shape is already verified end-to-end for all 3
   pipeline_modes and exercised by the full 27-run eval — adding a
   `cache_lookup` node would mean a new conditional edge and re-verifying the
   shape for a feature that's real but not core to the Critic thesis. The
   wrapper also makes the eval-harness bypass structural rather than a flag
   someone has to remember: `evals/run_eval.py` simply never imports
   `app.investigate`, so there's no `use_cache=False` to forget at a call site.
2. **Raw `psycopg`, not the already-installed-but-unused `sqlalchemy`.** One
   table, one INSERT — same "direct calls, no framework for its own sake"
   reasoning as the eval-harness-vs-promptfoo/ragas/deepeval/LangSmith
   decision above. `sqlalchemy` in requirements.txt is very likely a leftover
   from `impl-plan.md`'s earlier stack (same category as `GITHUB_TOKEN` in
   `.env.example`, see FAILURES.md #2) — left in place, just unused.
3. **24h TTL, fixed constant** (`memory/cache.py::CACHE_TTL_SECONDS`). Corpus
   is static for the capstone window, so staleness isn't a real risk; short
   enough not to quietly outlive the submission.

**Correctness constraint, not a style choice:** the Redis cache key includes
`pipeline_mode`. Without that, a `critic_on` answer could be served back for
a `baseline` lookup of the same question, silently corrupting the whole
comparative-eval story. `memory/test_cache.py` asserts this isolation
explicitly.

**Also fixed along the way:** `GraphState.latency_ms` was defined
(`app/schemas.py`) but never populated by any graph node — only
`evals/run_eval.py`'s own external timer ever measured latency, so the
audit trail's `latency_ms` column would have always been 0.0. Added
`started_at` (stamped by `input_guardrail`), and `memory_write` now computes
a real elapsed time from it.

**Found during verification, not caused by this change:** the Streamlit UI
was already running on port 8501 from a *stray process on the global Python
install*, not `.venv`. It rendered the app fine (global env happened to have
the same packages) but its writes were going somewhere unverifiable — see
FAILURES.md #16.

### 2026-09-27 — Reviving GitHub MCP for real code reads (revises CLAUDE.md's "not GitHub" call)
CLAUDE.md's architecture section explicitly says the existing MCP server is
"the official Filesystem MCP server (**not GitHub** — there's no real hosted
repo)." That was true when CLAUDE.md was written. It no longer is:
`orderflow-app/` has since been pushed to a real repo
(`github.com/PrabuRepo/orderflow-app`, confirmed via `git remote -v`) — see
Housekeeping's "git — orderflow-app/" row. Discussed at length with the user
in chat before proceeding, not a silent reversal.

**What this replaces:** the earlier "Filesystem MCP server, paused on
Node.js" plan (Core pipeline item 1b) is superseded by this — both existed
to let an agent read real OrderFlow source text (not just AST structural
facts) for citation-grade evidence; GitHub MCP does the same job against the
now-real hosted repo instead of local disk, and needs no Node.js at all
(the official GitHub MCP server is written in Go, not TypeScript).

**Remote hosted server + scoped read-only PAT, not local Docker,** chosen for:
- Zero new infrastructure before the deadline — no container to pull/manage,
  no subprocess-spawn latency on top of the network call GitHub makes anyway.
- The safety property local Docker's `--read-only` flag would give (write
  tools unusable) is achievable identically via PAT scoping: a fine-grained
  PAT with only "Contents: Read-only" on `orderflow-app` gets any write
  attempt rejected server-side by GitHub itself, regardless of which server
  relays the call.
- PAT auth to the remote endpoint (`api.githubcopilot.com/mcp/`) does not
  require a GitHub Copilot subscription — only the OAuth login path does.
  Standard GitHub API rate limit applies (~5,000 req/hr per PAT), far more
  than this project needs. (Confirmed via GitHub's own README/remote-server
  docs plus one secondary source for the exact rate-limit figure — see chat.)
- Honest trade-off accepted: this is the first HTTP/SSE-transport MCP client
  in the codebase (`ast_client.py` only does stdio-subprocess). Small,
  not a functional risk.

**Local Docker (`ghcr.io/github/github-mcp-server`) is not rejected, just
sequenced after** — user wants to explore it later for the stronger
server-level tool restriction (`--read-only`, `GITHUB_TOOLSETS`) once the
remote path is proven working.

**Not yet built:** the PAT (user generating it, steps given in chat, never
pasted into this session), `mcp_clients/github_client.py` (mirrors
`ast_client.py`'s shape, HTTP transport instead of stdio), where it plugs
into `app/retrieval.py`, and how a code-read result changes
`agents/evidence.py`'s grounding check. Trigger question type, most likely
`incident_rca` (INC-1001's real bug is the payoff case) — not yet decided
whether `impact_analysis` also gets it.

### 2026-09-27 — GitHub MCP integration built and verified (real code citations for INC-1001)
Built per the plan in the entry above: `mcp_clients/github_client.py` (new,
connects to `https://api.githubcopilot.com/mcp/` over streamable HTTP),
`mcp_clients/ast_client.py` extended (`ASTLookupResult.file_paths`, so
GitHub's fetch reuses AST's own name-matching rather than re-resolving
components independently), `app/retrieval.py` wired with a new
`QUESTION_TYPES_USING_GITHUB_TOOLS = {"incident_rca"}` (deliberately not
`impact_analysis` — that question type already has a free, deterministic
ground-truth check; adding a live GitHub call there would add cost/latency/a
new failure mode for no metric benefit).

**Real cost measured, not estimated:** the INC-1001 demo question through
`critic_on` took ~23s (vs ~9-16s for other critic_on runs earlier this
session) — each retry now makes both an AST call AND a GitHub call, and this
question triggered 2 retries. Worth a line in the docs' cost/latency
discussion, not just the RAG-vs-agentic trade-off already planned.

**Two real bugs found and fixed while wiring this up, not anticipated in the
plan** — see FAILURES.md #17 and #18 for full detail:
- The remote MCP server's default connection mode ("auto" protocol
  negotiation) threw `missing Mcp-Param-repo header` on the first tool call
  of a fresh session. Fixed with `Client(transport, mode="legacy")`.
- `supervisor`'s keyword stub set `target_component=None` for EVERY
  `incident_rca` question — meaning the actual INC-1001 demo question
  ("charged twice") would never have resolved to `PaymentClient` at all,
  silently skipping the GitHub fetch. Gave it the same stub-quality fallback
  guess `impact_analysis` already had.

**Verified for real:** ran the full graph for the actual demo question,
confirmed `agents/evidence.py` cited real `payment_client.py` text with
`grounded=True`, confirmed `impact_analysis`'s behavior is unchanged
(`use_github_tools=False`), confirmed a bad/invalid token degrades to a
recorded error with RAG/AST evidence still flowing (no crash), and confirmed
no regressions in `agents.test_evidence`/`agents.test_critic`/
`mcp_servers.test_ast_server`/`memory.test_db`/`memory.test_cache`.

**Not yet done:** re-running `evals/run_eval.py` to see whether D1/D2 (the
two questions FAILURES.md/evals/dataset.py flagged as unverifiable against
real code) actually improve now that this exists. Worth doing before it goes
in the docs' eval tables.

### 2026-09-27 — Eval re-run with GitHub MCP active: confirmed working, and a real variance finding
Full 27-run + 4-error-case re-run after the GitHub MCP integration. Confirmed
working as intended: D2/B1/B6 (`incident_rca`) now show `+ GitHub source
read` in retrieval logs and cite `app/payment_client.py`/`app/inventory_client.py`
directly with `grounded=True` citations. All 4 error-handling cases still
pass, including Qdrant-down on an `incident_rca` question (GitHub/AST chunks
present, RAG chunks absent, correctly escalated anyway).

| Metric | baseline | critic_off | critic_on |
|---|---|---|---|
| False-confidence rate | 0.429 | **0.143** | 0.286 |
| Error-catch rate (planted traps) | 0.5 | 0.75 | 0.75 |
| Citation accuracy (LLM judge) | 0.774 | 0.816 | 0.828 |
| Citation grounding rate (mechanical) | — | 0.981 | 1.0 |
| Escalation rate | 0.0 | 0.0 | 0.444 |
| Mean tokens / mean latency | 1294 / 3.8s | 2542 / 5.1s | 9367 / 14.7s |

**The headline number moved, and it's worth being honest about why rather
than re-running until it looks better:** `critic_on`'s false-confidence rate
went from the first run's 0.143 (lowest of the 3) to 0.286 here (now higher
than `critic_off`'s 0.143). Pulled the judge's actual reasoning for both
flagged cases rather than trust the aggregate number blindly:
- **B6** ("can retries ever cause a duplicate charge, per requirements?" —
  `expected_behavior=CONFIDENT_ANSWER`, not a trap) — `critic_on` escalated
  (confidence=0.40) instead of giving the documented confident answer. The
  judge's own reasoning: *"overly cautious... defers instead of giving the
  documented confident conclusion."* This is scored under `false_confidence`
  but is actually the OPPOSITE failure mode — the same Critic over-caution
  FAILURES.md #13 already documented on an Impact Analysis question, now
  showing up on a business_functional one too. Not a new bug; a second data
  point for an already-known pattern.
- **B5** (refund hallucination trap) — `critic_on` gave a confident,
  ungrounded answer this time. The FIRST eval run's Decisions log entry
  specifically praised `critic_on` for catching this exact trap ("the
  clearest single data point in favor of the Critic"). This run, it didn't.
  Textbook single-trial LLM sampling variance — exactly what FAILURES.md
  #11 predicted would happen and why it argued for trials, not anecdotes.

**Action, not just observation:** this is now the SECOND time a single-trial
number has visibly flipped between runs on real data, not a hypothetical
risk. `--trials N` (already built into `evals/run_eval.py`) should run
before these numbers go into the docs as final — both `summary.md` and this
entry say so explicitly rather than let a favorable-looking single run stand
unquestioned.

**Fixed along the way, before running:** `mcp_clients/ast_client.py`'s "no
code component could be identified" case was wrongly recorded as a
`retrieval_errors` entry once `incident_rca` started using AST tools too —
this would have capped `confidence_gate`'s score at 0.4 for any incident
question that simply doesn't name a component (e.g. B2, a clean control
case), for a reason that has nothing to do with real system health. Caught
by testing the exact B2 question before running the full 27-run eval, not
after. See FAILURES.md #19.

## Explicitly deferred to after submission (per CLAUDE.md — do not build)

Reranker, HyDE, query-rewrite-as-a-step, ANN algorithm comparison, semantic
memory reuse, richer guardrails, a second vector DB, a standalone
LLM-as-judge lab exercise (separate from the in-project judge above).

**LangSmith evals** — the eval harness (#6) uses direct SDK calls, not a
framework (see Decisions log below for the comparison against promptfoo/
ragas/deepeval/LangSmith). User wants to explore LangSmith evals specifically
as a personal learning exercise after this project is submitted, since
langgraph is already the runtime here and tracing would be near-free to add —
a good comparison point against the custom harness once there's no deadline
pressure.
