# FAILURES.md — pivots, cuts, and bugs

Logged as they happen, not reconstructed later. Each entry: what happened,
why, what we did, and what it costs us.

## Scope cuts / pivots

### 1. "Tickets" knowledge domain cut entirely
- **What:** Planned 3 RAG domains (docs, incidents, tickets); shipped 2 (`docs`, `incidents`).
- **Why:** Sourcing a third corpus was the first thing cut to keep scope manageable.
- **Cost:** Less coverage of the "many source types" story. Trade-off to name in docs: per-domain collections vs. flat index is evaluated on 2 domains, not 3.

### 2. GitHub MCP server replaced by the official Filesystem MCP server
- **What:** The original plan specified the GitHub MCP server for live code reads. We used the Filesystem MCP server pointed at `orderflow-app/` instead.
- **Why:** OrderFlow was a synthetic app with no real hosted repo at the time, so there was nothing for GitHub MCP to read.
- **Cost:** None functionally. `.env` carried unused `GITHUB_TOKEN` / `GITHUB_TARGET_REPO` keys until this was reversed again (see TASKS.md's "Reviving GitHub MCP" entry) once `orderflow-app/` actually got a real hosted repo.

### 21. "Historical decisions" knowledge domain never built — unlike "tickets," never logged as cut
- **What:** `docs/onepager.md` §3 ("Data Surface") lists "historical decisions" as
  one of the knowledge base's potential content types, alongside architecture
  docs, runbooks, and incident reports. No such domain was ever built —
  no ADR-style file, nothing anywhere in `knowledge-domains/` covers it.
- **Why it's distinct from #1 ("tickets"):** tickets was a deliberate,
  explicitly-logged cut, made and recorded at the time. "Historical
  decisions" was never mentioned again after the onepager — not built, not
  cut on purpose, just silently absent. Found only by cross-checking the
  onepager's own claims against the real `knowledge-domains/` contents.
- **Cost:** Minor — nothing currently depends on it, and none of the 9 eval
  dataset questions need it. Worth a line in the docs deliverable's "what
  changed since the onepager" note (see TASKS.md's Problem Definition/Data
  Processing rubric cross-check entries) rather than silently leaving the
  onepager's claim unaddressed.

## Bugs found and fixed

### 3. Windows default encoding corrupted every ingested chunk
- **What:** `Path.read_text()` with no encoding uses cp1252 on Windows; the source markdown is UTF-8. Every em dash was stored and embedded as `â€”` (13 of 17 incident chunks affected, docs affected too).
- **How found:** Eyeballing `ingest.test_retrieval` output. Retrieval *ranking* still looked right, so this would have passed a purely score-based check.
- **Fix:** `encoding="utf-8"` in `ingest/run_ingestion.py` and `ingest/chunker.py`; re-ingested (upsert by id overwrites in place). Verified 0 mojibake in both collections.
- **Lesson:** Always pass `encoding="utf-8"` when reading files on this machine (AST server, eval harness, etc.), or set `PYTHONUTF8=1`.

### 4. `qdrant-client` 1.19.1 removed `.search()`
- **What:** `ingest/test_retrieval.py` raised `AttributeError: 'QdrantClient' object has no attribute 'search'`.
- **Fix:** Use `.query_points(collection_name=..., query=vector, limit=N).points`. It was the only call site.
- **Lesson:** Installed versions here are newer than most examples; check the client API before writing the real retriever.

### 5. OrderFlow source files were in the wrong directory
- **What:** `CLAUDE.md` says the app lives in `orderflow-app/app/`, but the files sat flat in `knowledge-domains/services/`. Their own imports (`from app.models import ...`) were written for the `orderflow-app/app/` layout and did not resolve where they were.
- **Fix:** Moved all 6 files to `orderflow-app/app/`; verified they parse and import.
- **Watch out:** OrderFlow's package is also named `app`, colliding with AppMind's `app/`. Keep them on separate import roots. The AST MCP server should parse statically rather than import.

### 6. `mcp` 2.x removed `FastMCP`
- **What:** Installed `mcp==2.2.0`. Every v1-era example (`from mcp.server.fastmcp import FastMCP`) raises `ModuleNotFoundError` on this version; the class is now `mcp.server.mcpserver.MCPServer`, and `mcp.server.fastmcp` is a stub that only raises.
- **How caught:** Read the installed package before writing the server instead of coding from memory, so it cost minutes rather than a failed run.
- **Related:** tool failures are raised as `ToolError` (from `mcp.server.mcpserver.exceptions`), which the SDK returns as `is_error=True` — this is how the eval's "bad tool call" case is detected.
- **Lesson:** Same as #4: installed versions are newer than most examples; check the real API first.

### 7. `baseline` mode did no retrieval — FIXED
- **What:** `route_after_supervisor` sent `baseline` straight to `synthesis`, so it had no context at all. A baseline like that would be a strawman and overstate the Critic's benefit.
- **Fix:** Added a separate `retriever` node (CLAUDE.md's architecture lists one). `baseline` now goes supervisor -> retriever -> synthesis, using the same first-pass plan as the other modes, so every mode sees identical retrieval and the eval isolates Evidence/Critic/Gate.

### 8. "Graceful" error handling first meant "didn't crash", not "escalated"
- **What:** With the AST MCP server dead, the first version recorded the error and did not crash — but the confidence gate still scored 1.00 and synthesized an answer to an impact question that had zero code evidence. My own test only asserted "no crash", so it passed.
- **How caught:** Reading the run output, not the PASS lines.
- **Fix:** Gate now caps confidence at 0.4 (below the 0.5 escalation threshold) when any retrieval error occurred, and forces 0.0 on zero evidence. Test now asserts escalation.
- **Lesson:** For this project "handled the error" means "escalated honestly". Write the assertion for the behaviour you want, not the absence of a crash.

### 12. Baseline brief had zero citations — FIXED
- **What:** The stub `synthesis` cited `state.evidence`, which baseline never builds (it skips the Evidence node), so baseline briefs showed no citations and tripped the output-guardrail warning on every run.
- **Fix:** `agents/synthesis.py`'s `synthesize_baseline_answer()` answers straight from `retrieved_chunks` and builds citations from the chunks it actually used, explicitly marked `grounded=False` (never verified — that gap is baseline's definition, not a defect in the citation itself). `output_guardrail` now passes for baseline too.

## Known limitations

### Retrieval (`app/retrieval.py`)
- The AST MCP server is spawned per impact question: measured ~0.9 s for retrieval with the AST call vs ~0.2 s for vector search alone (~4x). A persistent client would remove it; not worth the complexity for the demo. This is concrete evidence for the "agentic latency/cost vs RAG" trade-off.
- Relevance cutoff (0.25 cosine) was chosen from measured scores on this small corpus (off-topic <= 0.17, real questions >= 0.57); it would need re-tuning on a different corpus or embedding model.
- Component names for AST lookup are matched from the question text against the server's own component list (case/spacing-insensitive). A question naming several components looks up to 3; a question naming none falls back to the supervisor's guess.

### AST dependency server (`mcp_servers/ast_graph.py`)
- Static best-effort analysis: no inheritance/MRO, no dynamic dispatch, relative imports ignored, calls to code outside `orderflow-app/` dropped. Fine for OrderFlow (absolute imports, no inheritance); would need real type inference for a bigger codebase.
- Transitive `dependent_modules` beyond depth 1 follow any import of the previous module, so they over-approximate. `affected_symbols` (call-graph based) is the more precise blast-radius view.

## Open issues (not yet fixed)

### 9. Supervisor is still a keyword stub and misclassifies
- **What:** `supervisor` classifies with keyword checks. E.g. "Does OrderFlow reserve inventory before or after charging?" is labelled `incident_rca` because it contains "charge". `question_type` only sets top-k per collection today (both collections are always searched), so the damage is small — but it will matter once nodes branch on type.
- **Note:** Impact Analysis no longer depends on the supervisor's component guess: the retriever extracts the component from the question via the AST server's component list.
- **Plan:** Real (LLM-based) classification, alongside the other LLM nodes.

### 11. Critic is non-deterministic across identical runs — expected, and this IS the metric
- **What:** Running the exact same INC-1001 question ("why were customers charged twice?") through `critic_on` four times back to back produced 4 different outcomes: 3 correctly escalated (low/capped confidence, an unresolved `gap` flag noting the incident's own status is "root cause under investigation"), but 1 run resolved every flag and answered with confidence=1.00 — even though the underlying evidence (INC-1001 is explicitly still open) had not changed. That run is a false-confidence result.
- **Why this isn't "fixed" here:** This is LLM sampling variance in judgment, not a code bug (the mechanical parts — grounding checks, uncited-flag derivation, sticky unresolved-by-default flags — are deterministic and unit-tested, see `agents/test_evidence.py` + `agents/test_critic.py`). Prompt-tuned harder against this one question would overfit to it, which the Critic's prompt deliberately avoids (see module docstring). The right fix is measurement, not a single hand-tuned prompt: this rate, across many trials, is exactly what "false-confidence rate" (CLAUDE.md's must-have eval metric) is FOR.
- **Action:** Flag this explicitly in the docs' eval section — run enough trials per demo question to report a rate, not a single anecdote. Do not claim the Critic eliminates false confidence; claim it reduces its rate vs. baseline/critic_off, with the number to back it up.
- **Mitigation already in place:** `confidence_gate` never lets a single flag resolution alone reach the top score if retrieval/agent errors occurred (see #7's fix); the true fix for this specific failure mode (self-reversing on a re-read with no new evidence) would be requiring the resolution reason to cite what's NEW, which is a prompt refinement worth trying if eval numbers show it matters — not done here.
- **Now measured, not just anecdotal:** the eval harness (`evals/run_eval.py`) ran D2 for real: false_confidence=True for `baseline`/`critic_off`, False for `critic_on` in that single-trial run — consistent with, not a repeat of, the 4-run finding above. See TASKS.md's decisions log for the full run's numbers.

### 13. Impact Analysis: Critic can be over-cautious, not just under-cautious (found via the eval harness)
- **What:** On D3 ("what would be affected if we changed PaymentClient's retry logic?"), `critic_on` escalated instead of answering — the Critic judged the AST dependency data insufficient ("no dependency analysis beyond direct callers"), even though `baseline`/`critic_off` both answered the same question correctly (AST-verified: perfect component recall).
- **Why it matters:** every other finding so far has been the Critic catching UNDER-confidence (a mode answering when it shouldn't). This is the opposite: the Critic refusing to let a good, available, correctly-scoped answer through. Both are real costs — "retry cap vs. resolution completeness" (CLAUDE.md's own named trade-off) is exactly this tension.
- **Not fixed:** one run, not a pattern yet. Worth a line in the docs' Trade-offs section either way; worth re-checking once `--trials N` gives more than one data point.

### 14. `DecisionBrief.affected_components` only echoes `target_component`, not real dependents
- **What:** `graph.py`'s `synthesis()` sets `affected_components=[state.target_component]` — the ONE component the question was about, not the components an AST `get_dependents()` call says would actually be affected (e.g. `order_service`, `api`). The field's own docstring implies a list of multiple affected components; today it's always a list of exactly one.
- **How found:** designing the eval harness's deterministic Impact Analysis ground-truth check (`evals/run_eval.py`) — worked around it by checking the AST graph directly against the answer TEXT rather than trusting this field.
- **Not fixed:** low priority, doesn't block anything currently reading `DecisionBrief`. Fix would be: after synthesis, parse the "code"-collection chunk's `dependent_modules`/`affected_symbols` JSON (already computed, already in `retrieved_chunks`) into real short names, deterministically, no LLM needed.

### 15. Streamlit UI script name and invocation both broke `app/` package imports — FIXED
- **What:** `ui/app.py` failed with `ModuleNotFoundError: No module named 'app.graph'; 'app' is not a package` on first run. Two separate problems stacked:
  1. Naming the script `app.py` collided with the project's own top-level `app/` package — Streamlit adds the script's own directory to `sys.path`, so `import app` resolved to `ui/app.py` itself (a plain module) instead of `app/__init__.py` (a package), and `from app.graph import ...` failed against itself.
  2. After renaming to `ui/streamlit_app.py`, a second, different error (`No module named 'app'` at all) — invoking via the `streamlit.exe` console-script entry point doesn't add the working directory to `sys.path` the way `python -m` does, so the project root (where `app/` actually lives) was never importable.
- **Fix:** renamed to `ui/streamlit_app.py` (fixes #1); `.claude/launch.json` invokes `python -m streamlit run ui/streamlit_app.py` rather than the `streamlit.exe` entry point directly (fixes #2, standard `-m` semantics add the cwd to `sys.path`).
- **Lesson:** never name a script the same as an existing top-level package in the same project, regardless of directory — and prefer `python -m <tool>` over a tool's own console-script binary when the tool needs to import project-local code from the working directory.

### 16. Streamlit was running on the global Python install, not `.venv` — silently, for hours
- **What:** While verifying the Postgres/Redis wiring, a UI-submitted
  question produced a correct-looking answer in the browser but never showed up
  in the `investigations` table. The Streamlit process on port 8501 turned out
  to be `C:\Users\prabu\AppData\Local\Programs\Python\Python313\python.exe`,
  not `.venv\Scripts\python.exe` — likely started before the
  venv existed, or from a terminal that hadn't activated it. It rendered
  the app correctly (the global env happened to have the same packages
  installed) which is exactly what made it hard to notice: no crash, no
  error page, just an app that *looked* identical while running against an
  unverified environment.
- **How found:** Querying Postgres directly after a UI submission and getting
  zero rows back, then checking `Get-Process`'s `Path` for the PID holding
  the port — not something the browser or Streamlit's own UI would ever surface.
- **Fix:** Killed the stray process, restarted via `.claude/launch.json`'s
  `appmind-ui` config (`.venv\Scripts\python.exe -m streamlit run ...`),
  re-verified the same question now writes a real row.
- **Lesson:** A working-looking UI is not proof it's running the code or
  environment you think it is. When a change should have an observable
  side effect (a DB row, a file write), check the side effect directly
  rather than trusting that the page rendering correctly implies the rest
  of the path executed as expected — same principle as #8's "write the
  assertion for the behavior you want," applied to manual verification too.

### 17. Remote GitHub MCP server: `missing Mcp-Param-repo header` on a fresh session's first tool call
- **What:** `mcp_clients/github_client.py`'s first real call to
  `get_file_contents` raised `mcp.shared.exceptions.MCPError: header
  mismatch: missing Mcp-Param-repo header for parameter "repo"` — despite
  passing `repo` correctly in the JSON-RPC arguments, and despite an earlier
  manual scratch test succeeding with the identical argument shape.
- **How found:** The scratch test that worked had called `list_tools()`
  before `call_tool()` in the same session; the client module didn't.
  Reproduced the failure/success difference directly rather than guessing —
  confirmed calling `list_tools()` first avoids the error, then found a
  cleaner fix: `Client(transport, mode="legacy")` avoids it too, without the
  extra round-trip. Root cause is almost certainly the `mcp` package's
  default `mode="auto"` protocol-version probe negotiating a modern
  connection with SEP-2549 cache-parameter-header behavior
  that isn't correctly established before the very first call in a fresh
  session — not confirmed to that level of certainty, but the fix is.
- **Fix:** `_client()` in `mcp_clients/github_client.py` constructs
  `Client(transport, mode="legacy")` — forces the plain initialize handshake,
  sidesteps the modern-protocol negotiation entirely.
- **Lesson:** Same pattern as #4/#6: don't trust an assumption about a new
  SDK's default behavior just because a similar call worked once elsewhere —
  the difference (call order, in this case) can be the whole story. Test the
  exact call shape the real code will make, not a nearby one.

### 18. `supervisor`'s stub never guessed a `target_component` for incident_rca — would have silently skipped GitHub reads for the actual demo question
- **What:** While verifying the GitHub MCP integration, retrieval for
  "Why were customers charged twice for one order?" (the real INC-1001 demo
  question) came back with `errors: ['no code component could be identified
  in the question']` and zero GitHub chunks — even though the wiring itself
  was correct. `app/graph.py::supervisor()` set `target_component = None`
  unconditionally for every `incident_rca` question, only ever guessing one
  for `impact_analysis` (always "OrderService"). AST's own name-matching
  against the question text also failed — "charged twice" never says
  "PaymentClient" — and neither does the incident doc itself (checked: it
  only says "Payment gateway", never the class name), so widening the match
  to retrieved evidence text wouldn't have helped either.
- **How found:** Ran the real question through `app/retrieval.py::retrieve()`
  directly before trusting the full graph — an established
  "verify before build" habit — the empty-result error surfaced immediately
  rather than being masked by evidence/critic dressing up an otherwise-empty
  code retrieval.
- **Fix:** Gave `incident_rca` the same stub-quality fallback guess
  `impact_analysis` already had — a small keyword map ("charge"/"payment" ->
  PaymentClient, "invent"/"stock"/"oversell" -> InventoryClient), same level
  of primitiveness as the existing code, not a new abstraction.
- **Lesson:** A component-matching mechanism that only looks at the literal
  question text will systematically miss any question phrased in business
  language rather than code identifiers — which is exactly how a real user
  asks an incident question. Worth remembering if `supervisor`'s classifier
  ever becomes LLM-based (FAILURES.md #9's open item): the fallback-guess
  need doesn't go away just because classification gets smarter.

### 19. AST "no code component identified" wrongly treated as a `retrieval_errors` entry once incident_rca started using AST tools too
- **What:** Before re-running the full eval, tested B2 ("why were emails
  delayed") — a clean control question with no code component to identify —
  and found `retrieval_errors: ['no code component could be identified in
  the question']`. That string capped `confidence_gate`'s score at 0.4
  (`if state.retrieval_errors or state.agent_errors: score = min(score,
  0.4)`) for a question that isn't broken in any way; it just doesn't name a
  component, which is a completely valid outcome for many `incident_rca`
  questions.
- **Why this only surfaced now:** the message and the gate's penalty for it
  both predate this. It was harmless before because `impact_analysis`
  (the only question type that used AST tools until then) always has a
  `target_component` fallback (`supervisor` guesses "OrderService"
  unconditionally), so this branch never actually fired for any question in
  the dataset. Adding `incident_rca` to `QUESTION_TYPES_USING_AST_TOOLS`
  (needed for the GitHub MCP integration — see TASKS.md) reached this branch
  for the first time, for a question type where "no component named" is a
  routine, expected outcome, not a failure.
- **How found:** Tested the specific question directly through
  `app/retrieval.py::retrieve()` before running the full 27-run eval, not
  after — a habit of verifying the exact case rather than trusting the
  aggregate afterward.
- **Fix:** `mcp_clients/ast_client.py`'s `_call_ast_tools` no longer records
  anything in `errors` when no component can be matched and there's no
  fallback — it's a legitimate "nothing extra to add," not a system failure.
- **Lesson:** A field named `errors` doing double duty as "the audit trail
  of what happened" AND "the signal that caps confidence" means every new
  caller of that code path inherits the second meaning whether or not it's
  appropriate for that caller. Worth remembering if a third AST/GitHub
  caller (e.g. a future business_functional trigger) gets added later.

### 20. `orderflow-app/` missing entirely after the repo migration to `app-mind` — silently broke Impact Analysis AND Incident RCA's real-code citations
- **What:** After the project moved from `ai-capstone/` to a fresh `app-mind`
  repo (new git init, new GitHub remote), `orderflow-app/` — the synthetic
  target app the custom AST server analyzes — was never copied over. Not
  merged into `app/`, not moved elsewhere, genuinely absent from the new repo.
- **Blast radius, not obvious at a glance:** the AST server couldn't even
  start (`FileNotFoundError: AST root does not exist`), which broke
  `list_components`/`get_dependents`/`get_callers` entirely. That silently
  took down TWO capabilities, not one: Impact Analysis questions directly
  (D3/B4), and separately, Incident RCA's GitHub-sourced real-code citations
  (a key payoff of this project) — because that path
  resolves its target file *through* the AST server's `get_dependents` call
  (`ASTLookupResult.file_paths`) before ever reaching GitHub MCP. A working
  GitHub integration with a dead upstream dependency looks the same as a
  broken one from the outside.
- **How found:** A full regression run for an unrelated change (the
  guardrails work) included `mcp_servers.test_ast_server`, which failed with
  a clear, specific error rather than a vague timeout — the kind of thing
  that's easy to miss if you only spot-check the change you just made instead
  of running the full suite.
- **Discussed before fixing, not assumed:** the user pushed back on "just
  copy it over," asking why local access was needed at all given the
  "access code through MCP" principle already established for GitHub reads.
  Real answer, not just restating the fix: GitHub MCP and the AST server do
  different jobs — GitHub MCP fetches one file's text on demand (already
  fully remote); the AST server builds a *cross-file* dependency graph, which
  needs every file parsed together, not fetched one-at-a-time over a network
  API. CLAUDE.md's own wording already calls it an "offline AST walk" on
  purpose, not by oversight — same reason real static-analysis tools
  (CodeQL, SonarQube) clone a repo and analyze the checkout rather than call
  a file-fetch API per file during analysis.
- **Fix:** user copied `orderflow-app/` from the still-intact old
  `ai-capstone/` checkout into the new repo (verified the source was correct
  first). Re-ran the full regression suite after — AST server 14/14 again,
  both the impact_analysis and incident_rca-via-GitHub chains confirmed
  working end-to-end.
- **Lesson:** a manual folder-based repo migration doesn't get the same
  safety net a `git mv`/`git clone` gets — nothing complains about a missing
  directory until something tries to use it, and here that something (the
  AST server) was two capabilities removed from the thing that actually
  broke first. Run the FULL regression suite after any manual filesystem
  reorg, not just the tests for whatever you were actually changing.
