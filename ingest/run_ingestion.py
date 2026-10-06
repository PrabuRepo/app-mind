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

WHERE THE FOLDERS COME FROM:
The application profile (config/apps/<id>.yaml, see app_profile/) lists the
docs and incident locations under `sources.docs` / `sources.incidents`. Each
of those two groups is loaded into the Qdrant collection of the same name.

RUNNING THIS SCRIPT:
    python -m ingest.run_ingestion            # embed and load into Qdrant
    python -m ingest.run_ingestion --dry-run  # chunk only: print counts, no API or Qdrant calls
Requires: your .env file filled in with a real OPENAI_API_KEY, and your
Docker Qdrant container already running (confirmed via `docker ps`).
"""

from __future__ import annotations

import os
import pathlib
import sys

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app_profile import AppProfile, ProfileError
from app_profile.registry import PROJECT_ROOT, select_profile
from ingest.chunker import Chunk, chunk_markdown

# text-embedding-3-small always produces vectors of exactly this length.
# Qdrant needs to know this up front when a collection is created, because
# every vector stored in that collection must be the same size.
EMBEDDING_DIMENSIONS = 1536
EMBEDDING_MODEL = "text-embedding-3-small"

# The two RAG domains. Each is a `sources` group in the application profile AND
# the name of its own Qdrant collection (collection names stay fixed; see
# features/appmind-config/app-config-design.md, decision 4).
DOMAINS = ("docs", "incidents")


def domain_paths(profile: AppProfile, base_dir: pathlib.Path = PROJECT_ROOT) -> dict[str, list[pathlib.Path]]:
    """Domain -> the local files/folders the profile lists for it, resolved
    against `base_dir`. Several entries for one domain end up in one collection.

    A source given as a repository (`repo` + `paths`) is not supported by
    ingestion yet: failing loudly beats silently ingesting nothing."""
    result: dict[str, list[pathlib.Path]] = {}
    for domain in DOMAINS:
        paths = []
        for entry in getattr(profile.sources, domain):
            if entry.path is None:
                raise ProfileError(
                    f"sources.{domain}: repository sources ({entry.repo}) are not supported by ingestion yet; "
                    "use a local `path`"
                )
            paths.append(base_dir / entry.path)
        result[domain] = paths
    return result


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


def collect_chunks(locations: list[pathlib.Path]) -> list[Chunk]:
    """Chunk every .md file in the given folders (or the given .md files), in a
    stable order. Needs no network, so it is also what --dry-run uses."""
    all_chunks: list[Chunk] = []
    for location in locations:
        md_files = [location] if location.is_file() else sorted(location.glob("*.md"))
        for md_file in md_files:
            # Source files are UTF-8; without an explicit encoding, Windows
            # defaults to cp1252 and mangles em dashes etc. before embedding.
            text = md_file.read_text(encoding="utf-8")
            all_chunks.extend(chunk_markdown(text, source=md_file.name))
    return all_chunks


def load_domain(openai_client: OpenAI, qdrant_client: QdrantClient, domain: str, locations: list[pathlib.Path]) -> int:
    """
    Processes every .md file in one domain's locations end to end: chunk,
    embed, upsert into that domain's Qdrant collection. Returns the total
    number of chunks loaded, so the caller can print a useful summary.
    """
    ensure_collection(qdrant_client, domain)

    all_chunks = collect_chunks(locations)

    if not all_chunks:
        print(f"[ingest] WARNING: no chunks found in {', '.join(map(str, locations))} — check the path is correct")
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


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    profile = select_profile()
    sources = domain_paths(profile)
    print(f"[ingest] application profile: {profile.app.id}")

    if "--dry-run" in argv:
        for domain, locations in sources.items():
            print(f"[dry-run] {domain}: {len(collect_chunks(locations))} chunk(s)")
        return

    openai_client, qdrant_client = load_env_and_clients()
    total = 0
    for domain, locations in sources.items():
        total += load_domain(openai_client, qdrant_client, domain, locations)
    print(f"\nDone. {total} total chunk(s) loaded across {len(sources)} collection(s).")


if __name__ == "__main__":
    main()
