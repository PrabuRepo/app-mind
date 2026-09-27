"""
ingest/test_retrieval.py — sanity-check that ingestion actually worked, by
running one real search against each collection and eyeballing the results.

WHY THIS SCRIPT EXISTS SEPARATELY FROM run_ingestion.py:
Ingestion succeeding (no errors, "N chunks loaded" printed) only proves data
got WRITTEN. It doesn't prove the data is actually retrievable in a way
that makes sense — e.g. that a question about payments actually returns the
payment-related chunk, not a random unrelated one. Running one real query
per collection and reading the result by eye is a fast, cheap way to catch
an embedding/chunking mistake before it shows up three steps later as a
confusing failure inside the full agent graph.

RUNNING THIS SCRIPT:
    python -m ingest.test_retrieval
"""

from __future__ import annotations

from ingest.run_ingestion import load_env_and_clients

# One deliberately domain-specific test question per collection — chosen to
# have an obvious, unambiguous right answer in the corpus, so it's easy to
# tell by eye whether retrieval worked.
TEST_QUERIES = {
    "docs": "Does inventory get reserved before or after payment is charged?",
    "incidents": "Why were customers charged twice for one order?",
}


def embed_query(openai_client, text: str) -> list[float]:
    from ingest.run_ingestion import EMBEDDING_MODEL

    response = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=[text])
    return response.data[0].embedding


def main():
    openai_client, qdrant_client = load_env_and_clients()

    for collection, query in TEST_QUERIES.items():
        print(f"\n{'=' * 60}")
        print(f"Collection: {collection!r}  |  Query: {query!r}")
        print("=" * 60)

        query_vector = embed_query(openai_client, query)

        # .query_points() returns the top-N closest points by vector similarity,
        # each with a `.score` (higher = closer match for cosine distance)
        # and `.payload` (the metadata we stored at ingestion time). (It
        # replaced the older .search(), which newer qdrant-client removed.)
        results = qdrant_client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=2,
        ).points

        if not results:
            print("  No results — collection may be empty. Did ingestion run first?")
            continue

        for rank, hit in enumerate(results, start=1):
            print(f"\n  #{rank} (score={hit.score:.3f}) "
                  f"source={hit.payload['source']} heading={hit.payload['heading']!r}")
            print(f"  {hit.payload['text'][:200]}...")


if __name__ == "__main__":
    main()
