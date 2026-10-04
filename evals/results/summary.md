# AppMind comparative eval — summary

Generated 2026-09-28T03:21:15+00:00Z
Dataset: 9 questions (see evals/dataset.py) x 3 pipeline_modes

| Metric | baseline | critic_off | critic_on |
|---|---|---|---|
| False-confidence rate | 0.143 | 0.286 | 0.143 |
| Error-catch rate (planted traps) | 0.75 | 0.75 | 0.75 |
| Citation accuracy (LLM judge) | 0.743 | 0.829 | 0.804 |
| Citation grounding rate (mechanical) | — | 0.978 | 1.0 |
| Impact Analysis component recall | 1.0 | 0.5 | 0.5 |
| Escalation rate | 0.0 | 0.0 | 0.222 |
| Mean token usage (pipeline only, excludes judge cost) | 1286.333 | 2574.333 | 8090.444 |
| Mean LLM calls | 1 | 2 | 4.778 |
| Mean latency (ms) | 2582.3 | 3930.122 | 9381.367 |

## Error-handling cases (reused from app/test_research_retriever.py)

4/4 passing — dead MCP server, hung MCP server, Qdrant unreachable, and empty/off-topic retrieval all degrade gracefully.

## Notes
- Recall@K and escalation-accuracy metrics are not implemented (cut per CLAUDE.md's priority list).
- The LLM judge is itself an LLM call with its own variance — its verdicts are a second opinion, not ground truth (same caution FAILURES.md #11 raised about the Critic itself).
- D1 (business_functional) cannot be verified against real code: GitHub MCP reads only trigger for incident_rca questions. "Correct" there means appropriately uncertain given the tools this system actually has, not omniscient. D2/B1/B6 (incident_rca) now DO get real code via GitHub MCP (mcp_clients/github_client.py) — reflected in the numbers above.
- 1 trial per (question, mode) — minimized for LLM-call cost on this capstone pass. A single run of a question won't re-surface the kind of variance FAILURES.md #11 found; add trials later (`--trials N`) if more coverage is needed.
