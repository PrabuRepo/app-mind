"""
mcp_clients/github_client.py — the MCP CLIENT for GitHub's remote-hosted MCP
server, used to fetch REAL source text (not just AST structural facts) for
citation-grade evidence on incident_rca questions.

Deliberately separate from mcp_clients/ast_client.py: that module resolves
WHICH files matter (name matching + dependency facts, via the local AST
server); this one only knows how to fetch a given file's actual content from
the real hosted orderflow-app repo. app/retrieval.py is the only caller,
chaining ast_client's file_paths into this module — same "one coordinator,
several single-purpose sources" shape rag/search.py and ast_client.py already
use.

Uses the REMOTE hosted GitHub MCP server (https://api.githubcopilot.com/mcp/)
over streamable HTTP, not a local subprocess — see TASKS.md's 2026-09-27
"Reviving GitHub MCP" decision for why (no Node.js/Docker needed; PAT auth to
this endpoint does not require a Copilot subscription). Read-only in
practice via the PAT's own scope (GITHUB_TOKEN must only ever be granted
"Contents: Read-only" on the target repo) — this module never calls a write
tool, but the real enforcement is GitHub rejecting a write from a read-scoped
token server-side, not client discipline alone.
"""

from __future__ import annotations

import asyncio
import functools
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from app.schemas import RetrievedChunk

GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/"
GITHUB_TIMEOUT_S = 20.0
MAX_FILES = 3   # cap how many files one question can pull, same spirit as ast_client.MAX_COMPONENTS


@dataclass
class GithubLookupResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@functools.lru_cache(maxsize=1)
def _config() -> tuple[str, str]:
    load_dotenv()
    token = os.environ.get("GITHUB_TOKEN")
    target_repo = os.environ.get("GITHUB_TARGET_REPO")
    if not token or not target_repo:
        raise RuntimeError("GITHUB_TOKEN / GITHUB_TARGET_REPO not set in .env")
    return token, target_repo


def _client() -> Client:
    token, _ = _config()
    http_client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    transport = streamable_http_client(GITHUB_MCP_URL, http_client=http_client)
    # mode="legacy": the default "auto" mode probes for a modern protocol
    # version and, on a fresh session, raised "missing Mcp-Param-<name>
    # header" on the FIRST call_tool if it wasn't preceded by a list_tools
    # call in the same session (found empirically — see chat/TASKS.md,
    # 2026-09-27). Forcing the plain initialize handshake sidesteps that
    # negotiation entirely rather than paying for an extra round-trip.
    return Client(transport, mode="legacy")


def _extract_text(tool_result) -> str | None:
    """The real file text comes back as an EmbeddedResource content block,
    NOT the leading TextContent block (which is just a status message like
    "successfully downloaded text file (SHA: ...)"). Found by inspecting the
    actual response shape empirically (see chat/TASKS.md, 2026-09-27) rather
    than assuming content[0].text — the obvious guess was wrong."""
    for block in tool_result.content:
        resource = getattr(block, "resource", None)
        if resource is not None and getattr(resource, "text", None):
            return resource.text
    return None


async def _fetch_files(paths: list[str]) -> GithubLookupResult:
    result = GithubLookupResult()
    _, target_repo = _config()
    owner, repo = target_repo.split("/", 1)
    async with _client() as client:
        for path in paths[:MAX_FILES]:
            tool_result = await client.call_tool("get_file_contents", {"owner": owner, "repo": repo, "path": path})
            if tool_result.is_error:
                detail = tool_result.content[0].text if tool_result.content else "unknown error"
                result.errors.append(f"GitHub get_file_contents({path!r}) failed: {detail}")
                continue
            text = _extract_text(tool_result)
            if text is None:
                result.errors.append(f"GitHub get_file_contents({path!r}) returned no readable content")
                continue
            result.chunks.append(RetrievedChunk(
                collection="code", source="github:get_file_contents", location=path, text=text,
            ))
    return result


def fetch_source_files(paths: list[str]) -> GithubLookupResult:
    """Public entry point: fetch real source text for up to MAX_FILES paths
    from the target repo. Raises on a timeout or connection failure —
    app/retrieval.py is responsible for catching that and degrading, same
    convention as mcp_clients.ast_client.lookup_dependents."""
    async def bounded_call() -> GithubLookupResult:
        return await asyncio.wait_for(_fetch_files(paths), GITHUB_TIMEOUT_S)
    return asyncio.run(bounded_call())
