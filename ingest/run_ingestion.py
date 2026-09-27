"""
ingest/run_ingestion.py — the full pipeline: read files -> chunk -> embed -> load into Qdrant.

WHAT "EMBEDDING" ACTUALLY MEANS:
An embedding model turns a piece of text into a list of numbers (a vector) —
for OpenAI's text-embedding-3-small, 1536 numbers per chunk. Texts with
similar MEANING end up as vectors that are numerically close together, even
if they don't share exact words. That's what makes semantic search possible:
instead of matching keywords, Qdrant compares vectors and returns whichever
stored chunks are numerically closest to your question's own vector.

WHAT QDRANT DOES WITH THOSE VECTORS:
Qdrant is a vector database — it stores each chunk's vector alongside a
"payload" (arbitrary metadata you attach: the chunk's text, source file,
heading) and can very quickly answer "give me the N stored vectors closest
to THIS query vector." A "collection" in Qdrant is roughly like a table in
a normal database — we use two collections, `docs` and `incidents`, kept
separate on purpose (see your one-pager's differentiator: per-domain
indexes, not one flat bucket).

RUNNING THIS SCRIPT:
    python -m ingest.run_ingestion
Requires: your .env file filled in with a real OPENAI_API_KEY, and your
Docker Qdrant container already running (confirmed via `docker ps`).
"""

from __future__ import annotations

import os
import pathlib

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from ingest.chunker import Chunk, chunk_markdown

# text-embedding-3-small always produces vectors of exactly this length.
# Qdrant needs to know this up front when a collection is created, because
# every vector stored in that collection must be the same size.
EMBEDDING_DIMENSIONS = 1536
EMBEDDING_MODEL = "text-embedding-3-small"

# Maps each knowledge domain to its own folder AND its own Qdrant collection
# name. Adding a third domain later (if you ever revisit that decision) is
# just one more line here — nothing else in this script needs to change.
DOMAIN_FOLDERS = {
    "docs": "knowledge-domains/docs",
    "incidents": "knowledge-domains/incidents",
}


def load_env_and_clients() -> tuple[OpenAI, QdrantClient]:
    """
    Reads .env (via python-dotenv) so os.environ has your real API key and
    Qdrant URL available, then constructs both clients. Keeping this in one
    function means there's exactly one place in the whole ingestion
    pipeline that knows HOW to connect to these services — useful if you
    ever need to change a URL or add auth later.
    """
    load_dotenv()
    openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    qdrant_client = QdrantClient(url=os.environ.get("QDRANT_URL", "http://localhost:6333"))
    return openai_client, qdrant_client


def ensure_collection(qdrant_client: QdrantClient, name: str) -> None:
    """
    Creates a Qdrant collection if it doesn't already exist. `Distance.COSINE`
    tells Qdrant to measure "closeness" between vectors using cosine
    similarity (the angle between two vectors) rather than raw Euclidean
    distance — cosine is the standard choice for text embeddings, because
    it cares about DIRECTION (meaning) rather than magnitude (roughly,
    text length), which is what you want for semantic search.
    """
    existing = [c.name for c in qdrant_client.get_collections().collections]
    if name in existing:
        print(f"[qdrant] collection {name!r} already exists — reusing it")
        return
    qdrant_client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=EMBEDDING_DIMENSIONS, distance=Distance.COSINE),
    )
    print(f"[qdrant] created collection {name!r}")


def embed_chunks(openai_client: OpenAI, chunks: list[Chunk]) -> list[list[float]]:
    """
    Sends every chunk's text to OpenAI's embeddings endpoint IN ONE BATCH
    CALL rather than one call per chunk. This matters for two reasons:
    it's meaningfully faster (one network round-trip instead of N), and
    it's part of why your cost/latency eval metric matters — batching is a
    real, simple optimization worth having in your docs' Trade-offs section.
    """
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[c.text for c in chunks],
    )
    # response.data is returned in the SAME ORDER as the input list, so
    # zipping it back up with `chunks` by index is safe.
    return [item.embedding for item in response.data]


def load_domain(openai_client: OpenAI, qdrant_client: QdrantClient, domain: str, folder: str) -> int:
    """
    Processes every .md file in one domain's folder end to end: chunk,
    embed, upsert into that domain's Qdrant collection. Returns the total
    number of chunks loaded, so the caller can print a useful summary.
    """
    ensure_collection(qdrant_client, domain)

    folder_path = pathlib.Path(folder)
    all_chunks: list[Chunk] = []
    for md_file in sorted(folder_path.glob("*.md")):
        # Source files are UTF-8; without an explicit encoding, Windows
        # defaults to cp1252 and mangles em dashes etc. before embedding.
        text = md_file.read_text(encoding="utf-8")
        all_chunks.extend(chunk_markdown(text, source=md_file.name))

    if not all_chunks:
        print(f"[ingest] WARNING: no chunks found in {folder} — check the path is correct")
        return 0

    vectors = embed_chunks(openai_client, all_chunks)

    # A PointStruct is Qdrant's unit of storage: an id, a vector, and a
    # payload (metadata). We use a simple incrementing integer id here —
    # fine for a corpus this small; a real production system would use a
    # stable id derived from (source, heading) so re-running ingestion
    # updates existing points instead of creating duplicates.
    points = [
        PointStruct(
            id=idx,
            vector=vector,
            payload={"text": chunk.text, "source": chunk.source, "heading": chunk.heading},
        )
        for idx, (chunk, vector) in enumerate(zip(all_chunks, vectors))
    ]

    qdrant_client.upsert(collection_name=domain, points=points)
    print(f"[ingest] loaded {len(points)} chunk(s) into collection {domain!r}")
    return len(points)


def main():
    openai_client, qdrant_client = load_env_and_clients()
    total = 0
    for domain, folder in DOMAIN_FOLDERS.items():
        total += load_domain(openai_client, qdrant_client, domain, folder)
    print(f"\nDone. {total} total chunk(s) loaded across {len(DOMAIN_FOLDERS)} collection(s).")


if __name__ == "__main__":
    main()
