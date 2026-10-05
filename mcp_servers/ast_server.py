"""
mcp_servers/ast_server.py — the CUSTOM MCP server: exposes a code snapshot's
dependency/call graph (code_context/graph.py) as tools an agent can call.

WHAT MCP IS, BRIEFLY:
MCP (Model Context Protocol) is a standard way for an agent to discover and
call tools that live in a separate process. The agent (the "client") starts
this program, asks "what tools do you have?", then calls them by name with
JSON arguments and gets JSON back. The tool implementation is hidden behind
that interface — the agent doesn't import our code, it just speaks MCP.
That separation is why a dead server is a real failure mode worth testing.

TOOLS (all read-only — this server can never modify the code it describes):
  list_components()                  what names exist (so the agent can pick a valid one)
  get_dependents(component, ...)     blast radius: modules + functions affected by a change
  get_callers(function, ...)         who calls this function/class

WHERE THE GRAPH COMES FROM:
The graph is built ahead of time by the separate indexer project and stored as
a snapshot (see indexer/CONTRACT.md). This server only LOADS one, from a JSON
file the caller passes in — it never parses source code and never needs
database credentials. That file is exported from the database by
code_context.snapshots.export_graph_file().

RUNNING IT:
    python -m mcp_servers.ast_server --snapshot PATH
Normally you don't run it by hand: an MCP client spawns it over stdio (see
test_ast_server.py). IMPORTANT: over stdio, stdout IS the protocol channel,
so this file must never print() — anything on stdout corrupts the stream.
Diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from code_context.contract import CodeContextError
from code_context.graph import CodeGraph, ComponentError


def _instructions(graph: CodeGraph) -> str:
    return (
        f"Static dependency analysis of {graph.repo or 'a code repository'}"
        f"{' at commit ' + graph.sha[:7] if graph.sha else ''}. "
        "Use list_components first if unsure of a name; names are matched loosely "
        "('PaymentClient', 'PaymentClient.charge', 'payment_client' all work). "
        "Results include file:line locations you can cite. This server only "
        "answers structural questions; it does not return source text."
    )


def load_graph(path: pathlib.Path | str) -> CodeGraph:
    return CodeGraph.from_dict(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))


def create_server(graph: CodeGraph) -> MCPServer:
    server = MCPServer("code-graph", instructions=_instructions(graph))

    def _or_tool_error(fn, *args) -> dict[str, Any]:
        # ToolError => the client gets is_error=True plus this message, which
        # the agent can read and self-correct from, instead of a crashed call.
        try:
            return fn(*args)
        except ComponentError as exc:
            hint = f" Did you mean: {', '.join(exc.suggestions)}?" if exc.suggestions else ""
            raise ToolError(f"{exc}{hint}") from exc

    @server.tool()
    def list_components() -> dict[str, Any]:
        """List every module, class, method and function in the analysed repository, with file paths."""
        return graph.list_components()

    @server.tool()
    def get_dependents(component: str, transitive: bool = True) -> dict[str, Any]:
        """What would be affected if `component` (a module, class, or function) changed?

        Returns dependent_modules (who imports it) and affected_symbols (which
        functions call into it), each with depth and file:line. transitive=True
        follows the chain outward (blast radius); False returns direct dependents only.
        """
        return _or_tool_error(graph.get_dependents, component, transitive)

    @server.tool()
    def get_callers(function: str, transitive: bool = False) -> dict[str, Any]:
        """Who calls `function` (or a class's constructor/methods), with call-site lines.

        transitive=False (default) returns direct callers only; True also
        returns callers of callers.
        """
        return _or_tool_error(graph.get_callers, function, transitive)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Code dependency graph MCP server (stdio)")
    parser.add_argument("--snapshot", required=True,
                        help="path to a graph snapshot JSON (indexer/CONTRACT.md, section 2)")
    args = parser.parse_args()
    try:
        server = create_server(load_graph(args.snapshot))
    except (OSError, ValueError, CodeContextError) as exc:   # unreadable file, bad JSON, unsupported version
        print(f"ast_server: cannot load snapshot {args.snapshot!r}: {exc}", file=sys.stderr)
        raise SystemExit(2)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
