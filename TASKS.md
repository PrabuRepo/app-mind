# TASKS.md — living status tracker

Updated as work happens — the living record of build status, distinct from
CLAUDE.md's current-state project description. Statuses: **Complete** /
**Pending** / **Paused** / **Superseded** / **TODO (later)**. See
[FAILURES.md](FAILURES.md) for *why* things changed shape; this file is only
*what state each piece is in*.

## Capstone evaluation rubric (`capstone-eval-metrics.png`) — cross-check

Transcribed from the image, then checked against the actual codebase (not
assumed from memory) before writing docs, so gaps get found now rather than
discovered by a grader.

| Rubric item | Sub-item | Status | Where it lives / what's missing |
|---|---|---|---|
| Problem definition | Scoping | Complete | `docs/onepager.md` (converted from `docs/onepager.txt`) explicitly states narrow scope: one app, 3 question types. A real, already-approved design document a grader reads — not just CLAUDE.md |
| Problem definition | Clarity | Partial — accepted as-is (Option A) | Prose is clear, but 4 unreconciled gaps vs. the actual build found on cross-check: (1) "Use cases" section names "Change-impact / will this fit review," never built, and never names "Incident/RCA," which was; (2) Success Metrics lists 5 metrics, only 3 built (Recall@K + Escalation Accuracy cut, see `summary.md`'s notes); (3) FastAPI named in stack, dropped; (4) "tickets" named as a data source, cut entirely (FAILURES.md #1). Deliberately not fixed in the onepager itself — deferred to a short "what changed since the onepager" note in the docs deliverable (#8) instead |
| Data Processing | Sources | Complete (code); §3 cross-checked, Option A | `knowledge-domains/docs` (3 files) + `knowledge-domains/incidents` (4 files), real ingestion (`ingest/run_ingestion.py`); code sources via the AST server (`orderflow-app/`) + GitHub MCP. Onepager §3 checked against real contents: 5/7 claims hold, "tickets" already tracked as cut (FAILURES.md #1), "historical decisions" was a new finding — never built, never logged — now logged as FAILURES.md #21. Same Option A treatment as Clarity: not fixed in the onepager, deferred to the docs deliverable's "what changed" note |
| Data Processing | Handling PII | Complete (code); statement still needed in #8 | `guardrails/input_guardrail.py` now actually detects PII-shaped input (email/phone/SSN regex) and blocks before any retrieval/LLM cost. A written PII statement (data is synthetic) for the docs deliverable is still separate, quick work |
| Data Processing | Guardrails | Complete | Both guardrails are real now, not stubs — see Decisions log "PII/Guardrails implementation" entry. Input: blocks PII-looking questions, routes to `escalate` before any cost. Output: replaces (not just warns about) an uncited non-escalation brief with an honest one. Off-topic questions deliberately NOT filtered at input — already handled correctly via empty-retrieval → confidence 0.0 → escalate (ERROR CASE 4) |
| System Design | Architecture | Complete (code), pending (docs) | Full LangGraph pipeline, 2 MCP servers (AST + GitHub), RAG, Postgres/Redis — all real and verified end-to-end. No architecture diagram/write-up yet for #8 |
| System Design | Trade Offs | **Scattered, not consolidated** | Real trade-off decisions exist throughout the Decisions log below (psycopg vs sqlalchemy, external cache wrapper vs graph node, remote vs local Docker MCP, etc.), and CLAUDE.md names 3 required ones explicitly (agentic latency/cost vs RAG, per-domain vs flat index, retry cap vs resolution completeness) — all demonstrated concretely in the eval numbers already. None of this has been pulled into an actual "Trade-offs" section yet |
| Evals | Task-specific | Complete | False-confidence rate, error-catch rate vs 4 planted traps, AST-deterministic Impact Analysis check (zero LLM cost), citation accuracy — bespoke to this project's real failure modes, not generic RAG metrics |
| Evals | Error handling | Complete | 4/4 fault-injection cases passing (dead MCP, hung MCP, Qdrant down, empty retrieval) — shared fixture reused across eval re-runs, not duplicated |
| Evals | Cost | Complete | `token_usage`/`mean_token_usage` tracked and reported per `pipeline_mode` |
| Evals | Latency | Complete | `latency_ms` is real (driven off `started_at`), reported per `pipeline_mode` |

**Bottom line:** Evals (all 4 sub-items), System Design architecture, and
Data Processing (Sources, Handling PII, Guardrails) are all genuinely
complete — real code, not stubs, verified end-to-end. Trade Offs remains the
one gap: real reasoning exists throughout the Decisions log below, but it
hasn't been consolidated into an actual "Trade-offs" section — that
consolidation now lives in `docs/documentation.md` §4.

## Core pipeline

| # | Item | Status | Note |
|---|---|---|---|
| — | Docker (Postgres, Qdrant, Redis) | Complete | all 3 containers confirmed running |
| — | `app/schemas.py` | Complete | includes `RetrievedChunk`, `ResearchPlan`, `agent_errors`, `llm_calls`, quote/resolution fields |
| — | LangGraph skeleton (`app/graph.py`) | Complete | shape + `pipeline_mode` routing verified for all 3 modes |
| — | Ingestion (`ingest/`) | Complete | ran; fixed a Windows cp1252 encoding bug and a `qdrant-client` API change along the way |
| 1a | Custom AST dependency-graph MCP server | Complete | `mcp_servers/ast_server.py` + `mcp_clients/ast_client.py`; 14/14 tests passing |
| 1b | Filesystem MCP server | **Superseded** | needs Node.js, still not installed on this machine — but this row is no longer just "paused waiting to resume": the underlying goal (real code text, not just AST structure) is now met by the GitHub MCP integration instead (see Housekeeping row below + Decisions log's "Reviving GitHub MCP" entry). Not expected to get built unless the target app ever lacks a real hosted repo again |
| 2 | Real `research`/`retriever` logic | Complete | `app/retrieval.py` + `rag/search.py`; baseline now actually retrieves (was a strawman before) |
| 3 | Real `evidence`/`critic` logic | Complete | `agents/evidence.py` + `agents/critic.py`; grounding checked in code, not trusted; flags are sticky across retries |
| 4 | Postgres `investigations` audit trail | Complete | `memory/db.py`; idempotent `CREATE TABLE IF NOT EXISTS`, one row per completed investigation, written from `memory_write`. Never raises — a dead Postgres degrades to a printed warning, not a crash. Verified against the real local container, not mocked (per CLAUDE.md) |
| 5 | Redis investigation-lookup cache | Complete | `memory/cache.py` + `app/investigate.py`; keyed on (normalized question, pipeline_mode) — mode is part of the key on purpose, see Decisions log. `evals/run_eval.py` deliberately never goes through this path (would corrupt the comparative eval's cost/latency numbers). `ui/streamlit_app.py` now calls `app.investigate.investigate()` instead of invoking the graph directly |
| 6a | Real `synthesis` logic (Step 0, discovered blocking #6) | Complete | `agents/synthesis.py`; was still the original stub — no eval metric can read answer *content* without this; baseline now genuinely answers + cites (unverified, `grounded=False`), critic_off/critic_on cite only verified evidence |
| 6b | Eval harness (`evals/`) | Complete | `evals/dataset.py` (9 questions), `llm_as_judge/judge.py`, `evals/run_eval.py`; ran the full set — results in `evals/results/runs.jsonl` + `summary.md`. See Decisions log for headline numbers and real findings |
| 7 | Streamlit UI | Complete (V1) | `ui/streamlit_app.py`; verified end-to-end in the browser (real question -> real escalation -> real citations rendered). Only imports `app.graph`/`app.schemas` — no direct dependency on `agents/`/`rag/`/`mcp_clients/`, same boundary `evals/run_eval.py` uses. V2 fast-follow (not built): pipeline_mode selector, critique-flag display, retrieval/agent-error display, cost/latency footer — deliberately deferred per user's "start simple" steer |
| 8 | Docs (4–5 pages) | Pending | blocked on #6 for the actual numbers; PII statement + Trade-offs section are "never cut" |
| 9 | Demo video (3 min) | Pending | blocked on #6 and #7 |
| 10 | `FAILURES.md` | Ongoing | actively maintained, 20 entries so far (numbered 1–21; #10 was retired at some point and never reused) |

## Housekeeping

| Item | Status | Note |
|---|---|---|
| Full reorg (`guardrails/`, `agents/`, `rag/`, `mcp_clients/`, `memory/`, `llm_as_judge/`, `evals/`) | Complete | all test suites re-verified passing after the move |
| `orderflow-app/` local checkout | **Removed** | Deleted from this repo (it was a gitignored standalone clone, verified clean and fully pushed first). The code is now read from the code index; see the Decisions log entry "Code knowledge index (Phase 1)" |
| git — `orderflow-app/` | Complete | committed to its own GitHub repo (`PrabuRepo/orderflow-app`), the only place the sample application lives |
| Code knowledge index: `indexer/` + `code_context/` | Complete (Phase 1) | A self-contained indexer project writes a SHA-pinned dependency graph and source files to Postgres; AppMind reads them through `code_context/`. Design and phases (2: multi-repo and docs, 3: automation, 4: split the indexer into its own repo) in `features/code-index-design.md` |
| git — `app-mind/` (the rest: `app/`, `agents/`, `ingest/`, etc.) | Complete | initialized and committed to its own GitHub repo |
| `llm_as_judge/` real implementation | Complete | `llm_as_judge/judge.py` is real and in active use by the eval harness, including its re-runs |
| "One command to run everything" — full containerization (`Dockerfile`, `docker-entrypoint.py`, `app` service in `docker-compose.yml`) | Complete | Reverses the earlier "decided NOT to dockerize the UI/app tier" call below, now that the project is past submission and the earlier reasons (active development churn, not in scope yet) no longer apply. `docker compose up --build -d` boots all 4 containers; the app container auto-ingests into Qdrant on first boot only (checks point counts first, so a restart doesn't silently re-embed). README documents both this path and the original local-venv path side by side. See Decisions log for the auto-ingest design call and two real bugs found while building it |
| GitHub MCP code-read integration (`mcp_clients/github_client.py`) | Complete | Remote hosted server + scoped read-only PAT, wired into `app/retrieval.py` for `incident_rca` questions only. Verified end-to-end through the real graph for the actual INC-1001 demo question: `critic_on` cites real `payment_client.py` text (grounded=True), including the literal "no idempotency key sent to the gateway" line — the concrete payoff this was built for. 11/11 checks passing in `mcp_clients/test_github_client.py` against the real remote server. No changes needed to `agents/evidence.py`'s grounding CODE — `is_grounded()` was already source-agnostic; only added one line to its LLM instructions about quoting raw source code. See Decisions log for two real gotchas found along the way |
| Local Docker GitHub MCP server (`ghcr.io/github/github-mcp-server`) | **Deferred, analysis done** | Remote hosted server stays the default. Researched and documented (setup steps, pros, cons, design call, verification plan) in the Decisions log entry "Local Docker GitHub MCP server: analysis only, remote stays default" — ready to implement whenever it's picked up |

## Decisions log

### Build order: eval harness (#6) before Postgres (#4) / Redis (#5)
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

### Eval framework: direct SDK calls, not promptfoo/ragas/deepeval/LangSmith
Compared all four against a custom harness. Rejected because each is built
around a generic metric shape (prompt-in/output-out, RAG faithfulness,
pytest-style hallucination scoring) while this project's actual deliverable
is bespoke metrics CLAUDE.md itself defines: false-confidence rate, error-
catch rate against 4 named planted traps, and a deterministic AST-verified
check for Impact Analysis — none of which map onto a framework's built-in
assertions. Would've meant writing the same custom judge logic anyway, wrapped
in a new dependency (and for LangSmith, a new account/API key) for no real
gain. `agents/evidence.py`/`agents/critic.py` already establish the
exact pattern needed (`structured_call` + a Pydantic schema) — the judge in
`llm_as_judge/` is just one more instance of that, zero new plumbing.
Matches CLAUDE.md's stated stack ("direct Anthropic/OpenAI SDK calls").

### Minimum LLM calls: 1 trial per (question, mode), not 3; 9 questions, not 11
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

### Eval harness built and run; headline numbers (1 trial, treat as directional)
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
  with `--trials N` for a sturdier headline figure.
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

### Postgres/Redis wiring: external cache wrapper, raw psycopg, 24h TTL
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

### Reviving GitHub MCP for real code reads (revises CLAUDE.md's "not GitHub" call)
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
- Zero new infrastructure to stand up — no container to pull/manage,
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

**Scope at the time of this decision:** the PAT (user-generated, kept out of
chat/session text), `mcp_clients/github_client.py` (mirrors
`ast_client.py`'s shape, HTTP transport instead of stdio), where it plugs
into `app/retrieval.py`, and how a code-read result changes
`agents/evidence.py`'s grounding check. Trigger question type: `incident_rca`
(INC-1001's real bug is the payoff case) — `impact_analysis` deliberately
does not use it (see Core pipeline table for final build status).

### GitHub MCP integration built and verified (real code citations for INC-1001)
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
`critic_on` took ~23s (vs ~9-16s for other critic_on runs) — each retry now
makes both an AST call AND a GitHub call, and this question triggered 2
retries. Worth a line in the docs' cost/latency discussion, not just the
RAG-vs-agentic trade-off already planned.

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

### Eval re-run with GitHub MCP active: confirmed working, and a real variance finding
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

### PII/Guardrails: real implementation, kept deliberately minimal
Both guardrails were literal no-op stubs (confirmed by rereading them fresh,
plus grepping the whole codebase for "PII" — the only hit was a docstring
comment citing this exact rubric line, no actual logic). Fixed with the
smallest change that makes them real:

- **Input guardrail**: 3 plain regex patterns (email, phone, SSN) — stdlib
  `re`, no LLM call, no new dependency. Deliberately scoped to PII only, not
  "off-topic" too: off-topic questions are already handled correctly by the
  existing empty-retrieval → `confidence_score=0.0` → escalate path (ERROR
  CASE 4, already passing) — a second, cruder keyword-based off-topic filter
  here would risk false-positiving a legitimate but unusually-phrased
  question for no real gain.
- **Blocking mechanism**: reused `escalate()` rather than adding a new node.
  2 new `GraphState` fields (`blocked`, `block_reason`), 1 new routing
  function (`route_after_input_guardrail`, same pattern as the 5 already in
  `graph.py`), the fixed `input_guardrail → supervisor` edge became
  conditional. No new node, no new file.
- **Output guardrail**: same check it already had (zero citations, not an
  escalation) — now actually replaces the brief with an honest fallback
  instead of printing a warning and shipping the uncited answer anyway.

**One real bug found and fixed during verification, not anticipated in the
plan:** the blocked-input brief's `answer` text didn't contain the word
"escalate", so the *existing* output_guardrail check (which detects
escalations by searching `answer`, not `confidence_rationale`) didn't
recognize it and overwrote the specific PII reason with a generic message.
Fixed by adjusting the blocked-brief's wording to match what the existing
check already looks for — a one-line fix, not a redesign of the detection
logic itself.

**Verified for real:** PII patterns tested against every real dataset
question (zero false positives), a live PII-containing question blocked
before any retrieval/LLM work (`llm_calls=0`, `token_usage=0`), full 3-mode
graph smoke test still passing, no regressions in any existing test suite.

### `orderflow-app/` was missing entirely after the repo migration; restored
Found while regression-testing the guardrails change (unrelated to it):
`mcp_servers.test_ast_server` failed with `AST root does not exist`. The new
`app-mind` repo had no `orderflow-app/` folder anywhere — not merged into
`app/`, not moved, genuinely absent. This broke the custom AST server
entirely (`list_components`/`get_dependents`/`get_callers` couldn't even
start), which silently broke two things: Impact Analysis questions
(D3/B4), and Incident RCA's GitHub code-read (which depends on AST
resolving a file path first — see the GitHub MCP entries above).

**Discussed before fixing, not assumed:** the user asked why a local copy
was needed at all, given the stated principle that code access should go
through MCP. Real answer: the custom AST server and the GitHub MCP client
do two different jobs. GitHub MCP fetches one file's text on demand for
citations — already fully remote, matches the principle. The AST server
builds a *cross-file* dependency/call graph, which needs every file parsed
together, not fetched one-at-a-time over the network — this is why
CLAUDE.md's own wording calls it an "offline AST walk" (deliberate, not an
oversight), and matches how real static-analysis tools work (clone, then
analyze locally, same reason CodeQL/SonarQube do it that way). Making the
AST server itself fully GitHub-MCP-native (fetch every file via
`get_file_contents` before parsing) is legitimate future work, not
something to build now — treated the same as the other
explicitly-deferred items below.

**Fix:** user copied `orderflow-app/` from the old `ai-capstone/` checkout
(source verified intact there first) into the new repo — purely additive,
matches CLAUDE.md's expected `orderflow-app/app/` layout exactly. Re-ran the
full regression after: AST server 14/14 again, both the impact_analysis and
incident_rca-via-GitHub chains confirmed working end-to-end, zero errors.

### Full containerization: auto-ingest on first boot, not a separate manual step
Revisits the "One command to run everything" row above, now that the project
is past submission. User asked specifically for a single `docker` command to
host the entire service, including dependencies — not just Postgres/Qdrant/
Redis (already containerized) but the app/UI tier too, which had been
deliberately left out earlier.

**Design fork, decided before building:** should the knowledge base load
into Qdrant automatically on first container boot, or stay a separate
documented command (`docker compose run app python -m ingest.run_ingestion`)?
Chose **automatic**, reasoning: the user's own framing — "the entire service
including all the dependencies" — makes the loaded corpus itself a
dependency the service needs to actually work. A separate manual step means
a fresh `docker compose up` boots a UI that escalates on literally every
question until someone remembers to run ingestion — not really "the entire
service," just the service plus a trap for whoever runs it next (a grader,
or future-self on a different machine). Avoided the obvious risk (a
check that silently skips ingestion when it shouldn't) by keeping it cheap
and conservative: `docker-entrypoint.py` queries Qdrant's `docs`/`incidents`
collections for point count and only skips ingestion if both are non-empty;
ingestion itself is already idempotent (upsert by id), so a false negative
costs a few seconds, not correctness.

**Two real things found while building this, not anticipated in the plan:**
- `requirements.txt` didn't exist in the working tree at all — deleted at
  some point during an earlier cleanup pass (git history shows it existed,
  current tree didn't), meaning the README's own `pip install -r
  requirements.txt` setup step was silently broken for a fresh clone. Fixed
  by regenerating it from the actual third-party imports across the
  codebase (9 packages: langgraph, mcp, openai, psycopg, pydantic,
  python-dotenv, qdrant-client, redis, streamlit) cross-referenced against
  the working `.venv`'s exact installed versions — not a raw `pip freeze`,
  which would have baked in confirmed-unused leftovers (`fastapi`,
  `sqlalchemy`, `langsmith`) into the Docker image.
- The app's `[llm]`/`[trace]`/`[mcp]` print-based logging (see the
  observability work logged implicitly in this file's recent history)
  didn't show up in `docker logs` at all — Python buffers stdout
  differently inside a container than in an interactive terminal. Fixed
  with `ENV PYTHONUNBUFFERED=1` in the `Dockerfile`.

**Verified for real, not just "should work":** removed 3 stale orphaned
containers from an earlier mismatched compose-project scope, then ran
`docker compose up --build -d` from a clean slate — confirmed auto-ingestion
fired (30 chunks loaded) on first boot, confirmed it correctly skipped
ingestion on a rebuild/restart with data already present, submitted two real
questions through the containerized UI via the browser (one triggering a
Critic retry), confirmed real rows landed in the Postgres audit trail and
Redis cache, and confirmed the full `[trace]`/`[llm]` logging streams live in
`docker compose logs -f app`.

**Also fixed while in the README, found not sought:** three dead links left
over from the `docs/` file renames (`documentation.md` → `detailed-design.md`,
`onepager.md` → `high-level-design.md`, `architecture_high_level.md` no
longer exists as a separate file) — the Full documentation line and one
Prerequisites footnote both pointed at files that no longer exist.

### Local Docker GitHub MCP server: analysis only, remote stays default
Researched, not built. The remote hosted server (`api.githubcopilot.com/mcp/`
via `mcp_clients/github_client.py`) remains the only GitHub MCP path in the
code. This entry records what a local self-hosted version would involve so
it can be picked up later without redoing the research.

**What it is:** the same official `github/github-mcp-server` software, run
locally in Docker instead of using GitHub's hosted deployment of it. It is
not a custom server — the project's only custom MCP server is the AST one.

**Setup steps (as documented by the server's README):**
1. Image: `ghcr.io/github/github-mcp-server`. Transport is **stdio** (run with
   `docker run -i`); no stable HTTP mode is documented in the README.
2. Auth: `GITHUB_PERSONAL_ACCESS_TOKEN` env var — the same fine-grained,
   read-only "Contents" PAT the remote path already uses.
3. Restriction, server-side: `GITHUB_READ_ONLY=1` and `GITHUB_TOOLSETS`
   (e.g. `repos`) or `GITHUB_TOOLS=get_file_contents` for the narrowest
   possible surface. Exact toolset containing `get_file_contents` should be
   confirmed when implementing.
4. Example invocation:
   ```
   docker run -i --rm \
     -e GITHUB_PERSONAL_ACCESS_TOKEN \
     -e GITHUB_READ_ONLY=1 \
     -e GITHUB_TOOLSETS=repos \
     ghcr.io/github/github-mcp-server
   ```
   Passing the token as `-e NAME` (no value) makes Docker read it from the
   spawning process's environment, so it never appears on the command line.

**How it would plug in:** a new `mcp_clients/github_client_local.py` with the
same interface as `github_client.py`, built like `ast_client.py` (spawn a
subprocess, speak MCP over stdio — `StdioServerParameters(command="docker",
args=[...])`). Selected by an env var, `APPMIND_GITHUB_MCP_MODE=remote|local`,
defaulting to `remote`, following the `APPMIND_LLM_MODEL` precedent in
`app/llm.py`, so nothing changes for anyone who doesn't opt in. The tool name
(`get_file_contents`) is the same on both servers. The remote client's
`mode="legacy"` workaround (FAILURES.md #17) is specific to the HTTP
transport and most likely not needed over stdio.

**Pros**
- **Write tools are never exposed, not just rejected.** Today safety is one
  layer: the read-only PAT makes GitHub reject write calls. Local adds a
  second: the write tools aren't registered with the client at all.
  (Whether the remote server offers an equivalent restriction could not be
  confirmed from the README; its separate remote docs may.)
- **Version pinning.** The image tag is chosen, so behavior doesn't change
  under the project. The remote server's behavior already caused one real
  bug (FAILURES.md #17).
- **No dependency on `api.githubcopilot.com/mcp/` specifically**, and a
  useful side-by-side comparison with the remote path.

**Cons**
- **Not offline.** The local server is a proxy that still calls GitHub's API
  with the PAT; only the dependency on the hosted MCP endpoint goes away.
- **Likely slower per lookup.** A `docker run` spawn per call adds startup
  latency, comparable to the AST server's measured ~0.9s subprocess spawn.
- **More moving parts:** Docker must be running and the image pulled.
- **Same PAT, same rate limits, same auth model** — no gain on those fronts.

**Design call: local-dev path only.** Spawning a sibling container from
inside the containerized `appmind-app` would require mounting the host's
`/var/run/docker.sock` and installing the Docker CLI in the image. That
gives the app container root-equivalent control over the host's Docker
daemon — too high a permanent cost for an exploratory comparison. The
containerized path keeps using the remote server. If a containerized local
server is ever wanted, the safer route is running it as its own compose
service over HTTP; reports on the server's repo suggest a newer `http`
command exists but that `--read-only` failed to restrict write tools under
it ([issue #2156](https://github.com/github/github-mcp-server/issues/2156)),
and that limiting tools in Docker has had problems
([issue #577](https://github.com/github/github-mcp-server/issues/577)) —
both unverified here, so treat read-only enforcement as something to test,
not assume.

**Verification plan when implemented:**
1. Call `list_tools()` against the local server and assert **no write tools
   are present** — this is the whole point of choosing it over remote.
2. Run the INC-1001 demo question through both modes; confirm both return
   the same real `payment_client.py` text and `grounded=True` citations.
3. Measure per-lookup latency for both and record it here.

Sources: [github/github-mcp-server README](https://github.com/github/github-mcp-server).

### Code knowledge index (Phase 1): local checkout removed
Implements `features/code-index-design.md` Phase 0 and Phase 1. The goal: stop
depending on a local copy of the target repository, so AppMind can support
other teams' repositories without copying them in, and take repository access
off the question-answering path.

**What was built**
- `indexer/` — a self-contained project (own README, `CONTRACT.md`, Dockerfile,
  requirements, tests). For each repo in `targets.toml` it resolves a commit
  SHA, downloads that commit as a tarball into a temp dir, builds the
  dependency/call graph, and writes graph + source files to Postgres in one
  transaction per repo. Unchanged commits are skipped; every run is audited.
- `code_context/` — AppMind's read-only view of that store (the only AppMind
  code that knows the data contract), including the query-side graph model.
- `mcp_servers/ast_server.py` now loads a snapshot file; `mcp_servers/ast_graph.py`
  was deleted (extraction moved into the indexer, queries into `code_context`).
- `app/retrieval.py` reads source text from the index instead of GitHub; the
  citation source is now `repo@sha7`. `ResearchPlan.use_github_tools` was
  renamed `use_source_files`. A one-shot `indexer` service was added to
  `docker-compose.yml`.

**Verified, not assumed**
- Phase 0 spike: GitHub's commit-SHA and tarball endpoints work with the
  existing read-only PAT; the MCP SDK starts a stdio child with a restricted
  environment (`get_default_environment() | server.env`), confirming that the
  AST server must receive a snapshot file, not database credentials.
- Parity with the old analyzer before it was deleted: the extractor's output
  is identical (29 symbols, 7 import edges, 17 call edges, same order), and
  116 query results (`get_dependents` and `get_callers`, both transitive modes,
  every one of the 29 components) are identical, as are the error suggestions.
- Tests all passing: the indexer suite (extractor, safe tarball extraction,
  store atomicity and pruning against real Postgres, orchestration, registry),
  `code_context` (graph, snapshots, failure modes), the AST server (14 checks
  over a real stdio connection), `app.test_research_retriever` including the 4
  fault-injection cases, and the agents/memory suites.
- `code_context/test_boundaries.py` guards the indexer boundary (no imports in
  either direction; the indexer imports only the standard library and its own
  requirements). Proven to fail by planting three deliberate violations.
- End to end through the containerized UI with `orderflow-app/` deleted: the
  INC-1001 question cites `PrabuRepo/orderflow-app@244ea40 — app/payment_client.py`
  (the retry bug), 0 retrieval errors, 0 ungrounded claims, no GitHub call.
- The eval harness's impact-analysis ground truth works from the snapshot
  (`APPMIND_EVAL_SNAPSHOT` pins it; the summary header records which one).

**Measured effect.** Reading a cited file's source text: **~1,315 ms** (remote
GitHub round trip, repeated on every Critic retry) → **~22 ms** (database
read), medians of 5. The AST lookup is unchanged at **~1.36 s**: the cost is
spawning the MCP server subprocess per lookup, not loading the graph. That is
now the dominant retrieval cost and the obvious next optimization (a persistent
server or an in-process provider).

**Deviations from the design doc, and why**
- The AST server's `--root` option was removed outright rather than kept for
  development: parsing code no longer lives in AppMind. Its tests run on a
  checked-in graph snapshot (`code_context/fixtures/orderflow_graph.json`,
  produced by the indexer's extractor), not on a copy of the service source;
  the sample source tree used to test the extractor lives inside `indexer/tests/`.
- Docs/specs indexing and the `repo_docs` collection stay in Phase 2 (a `docs`
  field in `targets.toml` is accepted and ignored with a notice).
- `mcp_clients/github_client.py` and its live tests were kept as an optional
  fallback but nothing on the default path calls it now.
- Fixed in passing: the stale `test_research_retriever` assertion that claimed
  only impact questions use the AST tools (incident questions deliberately do).

**Not done, stated plainly**
- The acceptance criterion "on clean volumes" was verified on the existing
  volumes, not after `docker compose down -v`, because that would also wipe the
  local audit trail and embeddings. Running it is a one-liner whenever wanted.
- The full 27-run eval was not re-run on the snapshot (it costs real LLM calls);
  only its ground-truth path was exercised.
- Phase 2 (multi-repo, docs, de-hardcoding OrderFlow from the supervisor and
  topic guardrail), Phase 3 (automation, GitHub App auth, freshness check) and
  Phase 4 (splitting `indexer/` into its own repository) remain.

## Explicitly deferred (do not build now)

Reranker, HyDE, query-rewrite-as-a-step, ANN algorithm comparison, semantic
memory reuse, richer guardrails, a second vector DB, a standalone
LLM-as-judge lab exercise (separate from the in-project judge above).

**LangSmith evals** — the eval harness (#6) uses direct SDK calls, not a
framework (see Decisions log above for the comparison against promptfoo/
ragas/deepeval/LangSmith). User wants to explore LangSmith evals specifically
as a personal learning exercise later, since langgraph is already the
runtime here and tracing would be near-free to add — a good comparison
point against the custom harness.
