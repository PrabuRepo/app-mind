"""
mcp_clients/ast_client.py — the MCP CLIENT for the custom AST dependency
server (mcp_servers/ast_server.py).

Deliberately a separate top-level package from mcp_servers/: that package
HOSTS tools over MCP; this one CALLS them, as a subprocess speaking stdio.
app/retrieval.py is the only caller — it treats this module the same way it
treats rag/search.py, as one of the two sources it merges into one
RetrievalResult.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field

from mcp import Client, StdioServerParameters

from app.schemas import RetrievedChunk

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# The custom AST MCP server, spawned as a subprocess per lookup. A module-level
# value so error-handling tests can swap in a dead one via monkeypatching.
AST_SERVER = StdioServerParameters(
    command=sys.executable,
    args=["-m", "mcp_servers.ast_server"],
    cwd=PROJECT_ROOT,
)
AST_TIMEOUT_S = 20.0
MAX_COMPONENTS = 3   # cap AST lookups if a question names many components
MIN_NAME_LENGTH = 6  # ignore short names ("Order", "api") — they match everywhere


@dataclass
class ASTLookupResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    target_component: str | None = None
    file_paths: list[str] = field(default_factory=list)
    # Where each matched component is actually defined (from get_dependents's
    # own "defined_in" field, e.g. "app/payment_client.py:12" -> the file
    # part). Consumed by mcp_clients.github_client to fetch real source text
    # for the same components this lookup already resolved — reuses this
    # module's name-matching instead of a second, separate resolution step.


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _mentioned_components(question: str, component_listing: dict) -> list[str]:
    """Which OrderFlow components does the question name? Matched against the
    server's own list_components() output (so there are no hardcoded names
    here), ignoring case and spacing: "PaymentClient", "payment client" and
    "payment_client" all match. Returned in the order they appear."""
    candidates: dict[str, str] = {}   # normalized name -> name to send to the tool
    for module in component_listing["modules"]:
        short_name = module["module"].rsplit(".", 1)[-1]
        candidates.setdefault(_normalize(short_name), short_name)
        for class_name in module["classes"]:
            candidates[_normalize(class_name)] = class_name   # a class overrides its same-named module

    normalized_question = _normalize(question)
    matches = [(normalized_question.find(norm), name) for norm, name in candidates.items()
               if len(norm) >= MIN_NAME_LENGTH and norm in normalized_question]
    return [name for _, name in sorted(matches)]


async def _call_ast_tools(question: str, fallback_component: str | None) -> ASTLookupResult:
    result = ASTLookupResult(target_component=fallback_component)
    async with Client(AST_SERVER) as client:
        listing = await client.call_tool("list_components", {})
        if listing.is_error:
            result.errors.append(f"AST list_components failed: {listing.content[0].text}")
            return result

        components = (_mentioned_components(question, listing.structured_content)
                     or ([fallback_component] if fallback_component else []))
        if not components:
            # NOT an error: many valid incident_rca questions (e.g. "why were
            # emails delayed") don't name a code component at all, and can
            # still be answered fine from RAG alone. Recording this as an
            # `errors` entry used to be harmless because impact_analysis
            # always has a fallback_component and this branch never fired for
            # it — now that incident_rca reaches here too (app/retrieval.py's
            # QUESTION_TYPES_USING_AST_TOOLS), it would wrongly cap
            # confidence_gate's score via `retrieval_errors`, treating "AST
            # correctly found nothing to add" the same as "Qdrant is down."
            # Found and fixed 2026-09-27 before re-running the eval harness —
            # see FAILURES.md.
            return result

        for name in components[:MAX_COMPONENTS]:
            tool_result = await client.call_tool("get_dependents", {"component": name})
            if tool_result.is_error:
                result.errors.append(f"AST get_dependents({name!r}) failed: {tool_result.content[0].text}")
                continue
            result.chunks.append(RetrievedChunk(
                collection="code",
                source="get_dependents",
                location=tool_result.structured_content["component"],
                text=json.dumps(tool_result.structured_content),
            ))
            defined_in = tool_result.structured_content.get("defined_in", "")
            file_path = defined_in.rsplit(":", 1)[0] if ":" in defined_in else None
            if file_path and file_path not in result.file_paths:
                result.file_paths.append(file_path)
        result.target_component = components[0]
    return result


def lookup_dependents(question: str, fallback_component: str | None) -> ASTLookupResult:
    """Public entry point: identify which OrderFlow component(s) the question
    names and fetch each one's dependents from the AST server, bounded by
    AST_TIMEOUT_S (read at call time, not baked in as a default argument, so a
    test can lower it via monkeypatching before calling). Raises on a timeout
    or a subprocess that never starts — app/retrieval.py is responsible for
    catching that and degrading gracefully."""
    async def bounded_call() -> ASTLookupResult:
        return await asyncio.wait_for(_call_ast_tools(question, fallback_component), AST_TIMEOUT_S)
    return asyncio.run(bounded_call())
