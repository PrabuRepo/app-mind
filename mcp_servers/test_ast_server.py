"""
mcp_servers/test_ast_server.py — end-to-end check of the AST MCP server over
a REAL stdio connection: this script spawns the server as a subprocess and
talks to it the way the agent will, so it exercises the actual protocol, not
just the underlying Python functions.

    python -m mcp_servers.test_ast_server

Each check prints PASS/FAIL; exits non-zero if anything fails. The expected
values are the facts about OrderFlow read from its source by hand:
  place_order (order_service.py:37) is the only caller of PaymentClient.charge;
  api.py:16 calls place_order; api.py imports OrderService.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

from mcp import Client, StdioServerParameters

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
# A graph snapshot of the sample application, produced once by the indexer's
# extractor (indexer/CONTRACT.md, schema v1). No source tree and no database
# needed to run this test.
GRAPH_FIXTURE = PROJECT_ROOT / "code_context" / "fixtures" / "orderflow_graph.json"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def symbols(entries: list[dict], depth: int | None = None) -> set[str]:
    return {e["symbol"] for e in entries if depth is None or e["depth"] == depth}


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.ast_server", "--snapshot", str(GRAPH_FIXTURE)],
        cwd=PROJECT_ROOT,
    )
    async with Client(params) as client:
        print("tools/list")
        tools = {t.name for t in (await client.list_tools()).tools}
        check("server exposes the 3 expected tools",
              tools == {"list_components", "get_dependents", "get_callers"}, str(tools))

        print("\nget_callers('PaymentClient.charge')  — direct")
        res = await client.call_tool("get_callers", {"function": "PaymentClient.charge"})
        data = res.structured_content
        check("call succeeded (is_error False)", not res.is_error)
        check("only direct caller is OrderService.place_order",
              symbols(data["callers"]) == {"app.order_service.OrderService.place_order"},
              str(symbols(data["callers"])))
        line = data["callers"][0]["call_sites"][0]["line"] if data["callers"] else None
        check("call site is order_service.py line 37", line == 37, str(line))

        print("\nget_callers('charge', transitive=True)  — loose name, callers of callers")
        res = await client.call_tool("get_callers", {"function": "charge", "transitive": True})
        data = res.structured_content
        check("loose name 'charge' resolves to PaymentClient.charge",
              data["function"] == "app.payment_client.PaymentClient.charge", data["function"])
        check("depth 2 reaches api.create_order",
              symbols(data["callers"], depth=2) == {"app.api.create_order"},
              str(symbols(data["callers"], depth=2)))

        print("\nget_dependents('PaymentClient')  — blast radius")
        data = (await client.call_tool("get_dependents", {"component": "PaymentClient"})).structured_content
        mods = {m["module"]: m["depth"] for m in data["dependent_modules"]}
        check("app.order_service imports it (depth 1)", mods.get("app.order_service") == 1, str(mods))
        check("app.api is reached transitively (depth 2)", mods.get("app.api") == 2, str(mods))
        check("app.inventory_client / notification_service are NOT dependents",
              not ({"app.inventory_client", "app.notification_service"} & set(mods)), str(mods))
        check("affected functions: place_order (1) then create_order (2)",
              symbols(data["affected_symbols"], 1) == {"app.order_service.OrderService.place_order",
                                                       "app.order_service.OrderService.__init__"}
              and symbols(data["affected_symbols"], 2) == {"app.api.create_order", "app.api"},
              str(symbols(data["affected_symbols"])))

        print("\nget_dependents('OrderService', transitive=False)  — the Impact Analysis demo target")
        data = (await client.call_tool("get_dependents",
                                       {"component": "OrderService", "transitive": False})).structured_content
        check("only app.api depends on OrderService",
              [m["module"] for m in data["dependent_modules"]] == ["app.api"],
              str([m["module"] for m in data["dependent_modules"]]))

        print("\nerror handling — unknown component")
        res = await client.call_tool("get_dependents", {"component": "PaymentClent"})
        text = res.content[0].text if res.content else ""
        check("returns is_error=True rather than crashing", bool(res.is_error))
        check("message suggests the right name", "PaymentClient" in text, text)

        print("\nerror handling — ambiguous component")
        res = await client.call_tool("get_callers", {"function": "__init__"})
        check("ambiguous name is refused, not guessed", bool(res.is_error))

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
