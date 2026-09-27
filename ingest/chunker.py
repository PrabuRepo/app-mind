"""
ingest/chunker.py — splits a markdown file into retrievable chunks.

WHY CHUNK AT ALL:
Embedding models turn text into vectors, but they work best on focused,
single-topic passages — not an entire multi-page document at once. If you
embed a whole document as one vector, a question about ONE specific detail
(e.g. "does inventory reserve before or after payment?") gets diluted by
everything else in the document. Chunking splits a doc into smaller,
independently-searchable pieces so retrieval can find the specific section
that actually answers a question.

WHY HEADING-BASED CHUNKING (as opposed to fixed-size, e.g. "every 500
characters"):
Fixed-size chunking is simpler to implement but can slice a sentence or an
idea in half arbitrarily. Every doc in `knowledge-domains/` is written with
clear `##` headings that already mark logical sections (see
architecture_overview.md's "## Components", "## Request flow", etc.) — so
splitting on those headings gives us chunks that are already coherent,
self-contained units of meaning, for free. This is a simple strategy, not
the only one — chunk-by-token-count and semantic chunking (using an LLM to
decide where ideas start/end) are two more sophisticated alternatives worth
knowing about, but heading-based is the right amount of complexity for a
corpus this small and this well-structured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    # The actual chunk content that will be embedded and searched over.

    source: str
    # Which file this chunk came from, e.g. "architecture_overview.md".
    # This becomes the `source` field on an EvidenceRecord later — it's
    # what makes a retrieved answer citable back to a real document.

    heading: str
    # The `##` heading this chunk fell under, e.g. "Components". Gives a
    # more precise citation than the filename alone (this becomes
    # EvidenceRecord.location).


def chunk_markdown(text: str, source: str) -> list[Chunk]:
    """
    Splits `text` on every line starting with `## ` (a level-2 markdown
    heading). Content before the first `## ` heading (e.g. a top-level `#`
    title and a short intro line) is kept as its own chunk labeled
    "Introduction", so nothing at the top of a file gets silently dropped.
    """
    # This regex means: "split the text right before any line that starts
    # with exactly two # characters followed by a space." The parentheses
    # around the pattern keep the heading line itself in the output list
    # (re.split normally discards whatever it matches on).
    pieces = re.split(r"(?m)^(## .+)$", text)

    chunks: list[Chunk] = []

    # pieces[0] is whatever came BEFORE the first ## heading (title + intro).
    intro = pieces[0].strip()
    if intro:
        chunks.append(Chunk(text=intro, source=source, heading="Introduction"))

    # After the intro, `pieces` alternates: [heading, content, heading, content, ...]
    # We step through two at a time to pair each heading with its content.
    for i in range(1, len(pieces), 2):
        heading_line = pieces[i].strip()
        heading_text = heading_line.lstrip("#").strip()
        content = pieces[i + 1].strip() if i + 1 < len(pieces) else ""
        full_chunk_text = f"{heading_line}\n{content}".strip()
        if full_chunk_text:
            chunks.append(Chunk(text=full_chunk_text, source=source, heading=heading_text))

    return chunks


# ---------------------------------------------------------------------------
# Manual sanity check — run `python -m ingest.chunker` from the project root
# to see exactly how one of your real files gets split, before wiring this
# into the full ingestion pipeline. Seeing the actual chunk boundaries is
# worth doing once by eye, so you trust the pipeline before trusting it
# blindly with your embedding budget.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import pathlib

    sample_path = pathlib.Path("knowledge-domains/docs/architecture_overview.md")
    text = sample_path.read_text(encoding="utf-8")
    chunks = chunk_markdown(text, source=sample_path.name)

    print(f"Split {sample_path.name} into {len(chunks)} chunk(s):\n")
    for idx, c in enumerate(chunks):
        print(f"--- Chunk {idx} | heading={c.heading!r} | {len(c.text)} chars ---")
        print(c.text[:150].replace("\n", " ") + ("..." if len(c.text) > 150 else ""))
        print()
