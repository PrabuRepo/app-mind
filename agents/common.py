"""agents/common.py — small pieces shared by every agent in this package.

Kept separate from evidence.py/critic.py/synthesis.py (rather than each
defining its own) for two reasons:
  - AgentOutput lets app/graph.py handle every agent's result identically:
    read `.items`, add `.tokens`/`.llm_calls` to the running state, surface
    `.error` the same way, regardless of which agent produced it.
  - The two `format_*_for_prompt` functions are used by more than one agent
    to render the SAME numbered list (evidence, or retrieved chunks) into a
    prompt. Both critic.py (reviewing evidence) and synthesis.py (writing the
    answer from evidence) show the model the identical numbering evidence.py
    used when it built citations — if that rendering ever drifted between
    two separately-maintained copies, an index in one agent's output could
    silently point at the wrong item in another's.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import EvidenceRecord, RetrievedChunk


@dataclass
class AgentOutput:
    items: list = field(default_factory=list)
    tokens: int = 0
    llm_calls: int = 0
    error: str | None = None


def format_evidence_for_prompt(evidence: list[EvidenceRecord]) -> str:
    """Render evidence claims as a numbered list an agent can refer back to
    by index (e.g. "I used claims [0] and [2]")."""
    return "\n\n".join(
        f"[{i}] source={e.source} | location={e.location} | verified={e.grounded}\n"
        f"claim: {e.claim}\nquote: {e.quote}"
        for i, e in enumerate(evidence)
    )


def format_chunks_for_prompt(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as a numbered list, same purpose as above but
    for raw (not yet claim-extracted) source material."""
    return "\n\n".join(
        f"[{i}] ({c.collection} | {c.source} | {c.location})\n{c.text}" for i, c in enumerate(chunks)
    )
