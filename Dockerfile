FROM python:3.13-slim

# Unbuffered stdout: without this, the app's [llm]/[trace]/[mcp] print-based
# logging (see FAILURES.md/TASKS.md's observability work) sits in a buffer
# instead of showing up live in `docker logs` / `docker compose logs`.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so a source change doesn't bust this layer's cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Everything else. The custom AST MCP server is spawned as a subprocess of the
# app (see mcp_clients/ast_client.py), not a separate container, so its code
# lives in this same image. It loads a code snapshot exported from Postgres —
# no target repository is ever copied into the image. The indexer
# (indexer/) is a separate project with its own image and is excluded via
# .dockerignore.
COPY . .

EXPOSE 8501

ENTRYPOINT ["python", "docker-entrypoint.py"]
