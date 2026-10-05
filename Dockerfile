FROM python:3.13-slim

# Unbuffered stdout: without this, the app's [llm]/[trace]/[mcp] print-based
# logging (see FAILURES.md/TASKS.md's observability work) sits in a buffer
# instead of showing up live in `docker logs` / `docker compose logs`.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so a source change doesn't bust this layer's cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Everything else, including orderflow-app/ — the custom AST MCP server is
# spawned as an in-process subprocess (see mcp_clients/ast_client.py), not a
# separate container, so it needs these files present in this same image.
COPY . .

EXPOSE 8501

ENTRYPOINT ["python", "docker-entrypoint.py"]
