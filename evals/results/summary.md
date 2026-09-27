# AppMind comparative eval — summary

Generated 2026-09-27T18:32:34+00:00Z
Dataset: 9 questions (see evals/dataset.py) x 3 pipeline_modes

| Metric | baseline | critic_off | critic_on |
|---|---|---|---|
| False-confidence rate | 0.429 | 0.143 | 0.286 |
| Error-catch rate (planted traps) | 0.5 | 0.75 | 0.75 |
| Citation accuracy (LLM judge) | 0.774 | 0.816 | 0.828 |
| Citation grounding rate (mechanical) | — | 0.981 | 1.0 |
| Impact Analysis component recall | 1.0 | 1.0 | 1.0 |
| Escalation rate | 0.0 | 0.0 | 0.444 |
| Mean token usage (pipeline only, excludes judge cost) | 1294.111 | 2542.111 | 9366.667 |
| Mean LLM calls | 1 | 2 | 5 |
| Mean latency (ms) | 3833.367 | 5083.967 | 14652.533 |

## Error-handling cases (reused from app/test_research_retriever.py)

4/4 passing — dead MCP server, hung MCP server, Qdrant unreachable, and empty/off-topic retrieval all degrade gracefully.

## Notes
- Recall@K and escalation-accuracy metrics are not implemented (cut per CLAUDE.md's priority list).
- The LLM judge is itself an LLM call with its own variance — its verdicts are a second opinion, not ground truth (same caution FAILURES.md #11 raised about the Critic itself).
- D1 (business_functional) cannot be verified against real code: GitHub MCP reads only trigger for incident_rca questions. "Correct" there means appropriately uncertain given the tools this system actually has, not omniscient. D2/B1/B6 (incident_rca) now DO get real code via GitHub MCP (mcp_clients/github_client.py) — reflected in the numbers above.
- False-confidence rate moved between this run and the previous one (critic_on: 0.143 → 0.286) — see TASKS.md's 2026-09-27 "eval re-run" entry for why: one flag (B6) is the Critic's already-documented OVER-caution failure mode (FAILURES.md #13), not the under-caution false-confidence problem the metric is named for, and one (B5) is genuine single-trial LLM sampling variance the Critic caught in the first run and missed in this one. Both are real findings, not artifacts of the GitHub MCP change — but they underscore why `--trials N` matters before these numbers go in the docs as final.
- 1 trial per (question, mode) — minimized for LLM-call cost on this capstone pass. A single run of a question won't re-surface the kind of variance FAILURES.md #11 found; add trials later (`--trials N`) if more coverage is needed.
