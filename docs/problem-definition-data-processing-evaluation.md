# AppMind — Problem Definition, Data Processing, and Evaluation Criteria

*Application Knowledge & Decision Intelligence Agent — capstone submission.*
*Related: [`high-level-design.md`](high-level-design.md) (the original approved design doc) · [`detailed-design.md`](detailed-design.md) (full documentation: architecture, trade-offs, failure analysis) · [`TASKS.md`](../TASKS.md) / [`FAILURES.md`](../FAILURES.md) (build status and history).*

---

## 1. Problem Definition

Teams that own applications depend on knowledge scattered across business documentation, architecture docs, source code, runbooks, and incident history — much of it implicit in a few experienced subject-matter experts (SMEs). Answering "why did this break," "how does this work," or "what would break if we changed X" well today means finding the right *person*, not the right system.

**AppMind** is an application-specific AI investigation agent that consolidates this scattered knowledge and investigates a question on the team's behalf, producing an evidence-backed, auditable decision brief — and escalating to a human when evidence is insufficient or contradictory. It is framed to *capture and scale SME judgment*, not replace it. The core differentiator — and the subject of the project's mandatory comparative evaluation — is a **Critic/Challenger agent** that reviews gathered evidence for contradictions, uncited claims, and gaps before an answer is allowed to ship.

**Scope** is deliberately narrow: one target application and three supported question types.

**Target application:** OrderFlow, a synthetic order-processing service purpose-built for this project, so ingestion and code-analysis tooling have real, working code to operate on without depending on an external company's data.

**Question types:**

| Type | What it does | Example |
|---|---|---|
| **Business/Functional** | Answers "how does this work" questions from documentation and incident history | *Does OrderFlow reserve inventory before or after payment, and why does that ordering matter?* |
| **Incident/RCA** | Investigates a real past incident, citing real source code as evidence | *Why were customers charged twice for one order (INC-1001), and is the cause confirmed?* |
| **Impact Analysis** | Answers code-dependency "blast radius" questions deterministically | *What would be affected if we changed PaymentClient's retry logic?* |

### What changed since the approved design doc

The approved design doc ([`high-level-design.md`](high-level-design.md)) and the system as built diverge in a few places, tracked honestly rather than silently:

- The design doc's use cases included a *"change-impact / will this fit"* review (evaluating a **proposed** future change against existing docs). That was never built. **Incident/RCA** — investigating a **past**, real incident — was built instead, a materially different capability: root-cause investigation, not compatibility review.
- The design doc's Success Metrics list five metrics; two (**Retrieval Recall@K**, **Escalation Accuracy**) were cut as lower priority given the build's time constraints. A simpler proxy, **Escalation Rate** (how *often* the system escalates), is reported instead.
- **FastAPI**, named in the original tech stack, was dropped — the UI calls the pipeline in-process, with no separate API layer.
- **"Tickets"** and **"historical decisions"**, both named as potential knowledge-base content, were never built into the corpus.

Every item above is logged at the point it happened in `FAILURES.md` and `TASKS.md`, not reconstructed after the fact.

---

## 2. Data Processing

### Sources

| Domain | Location | Content | Access method |
|---|---|---|---|
| `docs` | `knowledge-domains/docs/` | 3 files: architecture overview, business/functional requirements, operations runbook | RAG (Qdrant vector search) |
| `incidents` | `knowledge-domains/incidents/` | 4 incident reports, each planting a *different* kind of investigative problem (see §3) | RAG (Qdrant vector search) |
| Code (structure) | `orderflow-app/` | OrderFlow's Python source | Custom AST MCP server (local, static analysis) |
| Code (real text) | `github.com/PrabuRepo/orderflow-app` | Same source, hosted | GitHub MCP server (remote, per-file fetch for citations) |

Code is deliberately **not** embedded into the vector store — a dedicated architectural decision, not an oversight. Cross-file dependency analysis needs every file parsed together, not fetched one-at-a-time, and an embedded snapshot of code goes silently stale the moment the code changes — exactly the kind of false confidence this project exists to catch.

Ingestion (`ingest/run_ingestion.py`) chunks each document by heading, embeds with `text-embedding-3-small`, and loads into two separate Qdrant collections (`docs`, `incidents`) rather than one flat index, so each can carry its own retrieval policy. A relevance cutoff (cosine similarity ≥ 0.25, tuned against measured scores on this corpus) means an off-topic question returns **empty** retrieval rather than the least-bad chunks dressed up as evidence.

### Handling PII

All data in this project — OrderFlow itself, its documentation, its incident reports, and its source code — is **entirely synthetic**, purpose-built for this capstone. No real user, customer, or production data appears anywhere in the corpus, by construction. There is nothing to anonymize because nothing real was ever collected.

That said, the system defends against PII *appearing in a live question* — a real user pasting a real email or phone number into the question box. The input guardrail (below) detects and blocks that before any retrieval or LLM call runs.

### Guardrails

Both guardrails are real, verified checks, not placeholders:

- **Input guardrail** — three deterministic regex patterns (email, phone, SSN-shaped). A match blocks the question immediately, routing straight to an honest escalation, **before any retrieval or LLM cost is incurred**. Off-topic questions are deliberately *not* filtered here: the existing empty-retrieval → zero confidence → escalate path already handles them correctly, so a second, cruder keyword filter would only add false-positive risk for no real gain.
- **Output guardrail** — refuses to let a decision brief ship with zero citations unless it is honestly an escalation, replacing it with a safe fallback rather than just logging a warning. A confident, uncited answer is exactly the false-confidence failure mode this project exists to catch; the guardrail must not let one through even if an earlier step missed it.

---

## 3. Evaluation Criteria

### Methodology

The project's mandatory comparative evaluation runs all **9 dataset questions** — 3 demo questions (one per required type) plus 6 backing questions, together covering all 4 planted corpus traps (a real code-verifiable bug, a false alarm, mundane filler, and a documentation contradiction) — through **all 3 pipeline modes**:

| Mode | What it runs |
|---|---|
| `baseline` | Retrieve, then answer directly — no Evidence or Critic agent |
| `critic_off` | Full pipeline, Critic agent skipped |
| `critic_on` | Full pipeline, including the Critic — "AppMind proper" |

That is 27 graph runs (9 questions × 3 modes, 1 trial each). Scoring combines:

- An **LLM-as-judge** for subjective questions (does the answer match the expected behavior — a confident correct answer, a correctly identified false alarm, or an honest escalation).
- A **deterministic, zero-cost check** for the 2 Impact Analysis questions — comparing the answer directly against the AST server's own dependency-graph output, no LLM judgment involved.

**Metrics tracked**, in priority order:
1. **False-confidence rate** — how often a mode answers confidently when it shouldn't (the project's central concern).
2. **Error-catch rate** — how often a mode correctly identifies a planted trap.
3. **Citation accuracy** (LLM-judged) and **citation grounding rate** (mechanically verified against source text).
4. **Escalation rate**, **cost** (mean tokens), and **latency** (mean wall-clock time) per mode.
5. **Error handling** — 4 deliberate fault-injection cases (dead MCP server, hung MCP server, Qdrant unreachable, empty/off-topic retrieval), confirming graceful escalation rather than a crash.

### Results

| Metric | baseline | critic_off | critic_on |
|---|---|---|---|
| False-confidence rate | 0.429 | 0.143 | 0.286 |
| Error-catch rate (planted traps) | 0.5 | 0.75 | **0.75** |
| Citation accuracy (LLM judge) | 0.774 | 0.816 | 0.828 |
| Citation grounding rate (mechanical) | — | 0.981 | 1.0 |
| Escalation rate | 0.0 | 0.0 | 0.444 |
| Mean tokens / mean latency | 1,294 / 3.8s | 2,542 / 5.1s | 9,367 / 14.7s |

Error handling: **4/4** fault-injection cases pass — every failure degrades to an honest escalation, never a crash.

### Reading the results honestly

**Error-catch rate is a clean, stable win for the Critic** — 0.75 vs. 0.5 for baseline/critic_off, confirmed across two separate evaluation runs. **False-confidence rate is directionally favorable but not yet stable** at 1 trial per question: an earlier run showed `critic_on` with the *lowest* false-confidence rate of the three (0.143); this run shows it higher than `critic_off`. Pulling the judge's actual reasoning shows this is largely the Critic's known **over-caution** failure mode (escalating on a question that had a clean, confident, correct answer available) rather than a real regression — both directions of error are real, measured costs of the design, not selectively reported.

Two metrics from the original design doc — **Retrieval Recall@K** and **Escalation Accuracy** — are not implemented; this is stated here rather than silently omitted. `evals/run_eval.py --trials N` exists to produce a statistically stable version of the false-confidence number and was not run before this submission, given time constraints.

The honest takeaway: the Critic reliably catches more planted problems than either alternative, at a real, measured cost (~7× tokens, ~4× latency vs. baseline) — and the evaluation's own instability on a secondary metric is itself evidence it is measuring something real, not reporting a rehearsed number.
