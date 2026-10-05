"""
docker-entrypoint.py — the app container's startup script.

Two jobs, in order:
  1. Wait for Qdrant to actually be reachable (its container starting is not
     the same as it accepting connections yet — `depends_on` in
     docker-compose.yml only guarantees start order, not readiness).
  2. Auto-ingest the knowledge base into Qdrant on first boot only: checks
     whether `docs`/`incidents` already have points before running
     `ingest.run_ingestion`, so a container restart doesn't silently
     re-embed everything every time. Ingestion itself is idempotent anyway
     (upsert by id), so a false negative here just costs a few seconds, not
     correctness.

Then execs Streamlit (os.execvp, not subprocess.run) so it replaces this
process as PID 1 and receives signals (e.g. `docker stop`) directly, instead
of this script swallowing them while a child process keeps running.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

from qdrant_client import QdrantClient

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
REQUIRED_COLLECTIONS = ("docs", "incidents")
WAIT_TIMEOUT_S = 60


def _wait_for_qdrant() -> QdrantClient:
    client = QdrantClient(url=QDRANT_URL)
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while True:
        try:
            client.get_collections()
            return client
        except Exception as exc:
            if time.monotonic() > deadline:
                print(f"[entrypoint] Qdrant never became reachable at {QDRANT_URL}: {exc}", file=sys.stderr)
                raise
            print(f"[entrypoint] waiting for Qdrant at {QDRANT_URL}... ({type(exc).__name__})")
            time.sleep(2)


def _needs_ingestion(client: QdrantClient) -> bool:
    for name in REQUIRED_COLLECTIONS:
        try:
            if client.count(collection_name=name).count == 0:
                return True
        except Exception:
            return True  # collection doesn't exist yet
    return False


def main() -> None:
    client = _wait_for_qdrant()

    if _needs_ingestion(client):
        print("[entrypoint] knowledge base not loaded yet — running ingestion once")
        subprocess.run([sys.executable, "-m", "ingest.run_ingestion"], check=True)
    else:
        print("[entrypoint] knowledge base already loaded — skipping ingestion")

    print("[entrypoint] starting Streamlit")
    os.execvp(sys.executable, [
        sys.executable, "-m", "streamlit", "run", "ui/streamlit_app.py",
        "--server.address=0.0.0.0", "--server.port=8501",
    ])


if __name__ == "__main__":
    main()
