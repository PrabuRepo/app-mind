"""
code_context/graph.py — the QUERY side of a code graph snapshot.

A CodeGraph is rebuilt from the graph JSON the indexer stores (schema v1, see
indexer/CONTRACT.md) and answers the questions agents ask: what depends on a
component, who calls a function, what components exist. It never parses source
code — that is the indexer's job — so it needs no access to any repository.

"What depends on PaymentClient?" is a graph question with one correct answer:
same snapshot in, same answer out, no model involved, which is why this is a
tool and not a prompt (and why code is not in the vector store).

KNOWN LIMITS (inherited from the extractor, see CONTRACT.md): best-effort
static resolution — no inheritance/MRO, no dynamic dispatch, within one
repository only.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from dataclasses import dataclass, field

from code_context.contract import SUPPORTED_SCHEMA_VERSIONS, InvalidSnapshot, UnsupportedSchemaVersion


class ComponentError(ValueError):
    """A component name matched zero symbols, or matched more than one.

    Carries `suggestions` so the caller (an LLM, via the MCP tool) can retry
    with a valid name instead of dead-ending on a bare error string.
    """

    def __init__(self, message: str, suggestions: list[str] | None = None):
        super().__init__(message)
        self.suggestions = suggestions or []


@dataclass
class Symbol:
    qualname: str            # e.g. "app.payment_client.PaymentClient.charge"
    kind: str                # "module" | "class" | "function"
    module: str              # e.g. "app.payment_client"
    file: str                # repo-root-relative path, posix style
    line: int
    parent: str | None = None  # owning class qualname, for methods

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass
class ImportEdge:
    symbols: set[str] = field(default_factory=set)  # names pulled in via `from x import name`
    wholesale: bool = False                          # `import x` — could use anything in it
    line: int = 0


@dataclass
class CallSite:
    caller: str   # qualname of the calling function (or the module, for module-level code)
    target: str   # qualname of the function/class being called
    file: str
    line: int


class CodeGraph:
    def __init__(self, repo: str, sha: str, modules: set[str], symbols: dict[str, Symbol],
                 imports: dict[str, dict[str, ImportEdge]], call_sites: list[CallSite]):
        self.repo = repo
        self.sha = sha
        self.modules = modules
        self.symbols = symbols
        self.imports = imports
        self.call_sites = call_sites
        self._callers_by_target: dict[str, list[CallSite]] = defaultdict(list)
        for site in call_sites:
            self._callers_by_target[site.target].append(site)

    @classmethod
    def from_dict(cls, data: dict) -> "CodeGraph":
        """Rebuild a graph from the contract's graph JSON. Refuses a schema
        version it does not support, and a graph missing required fields."""
        version = data.get("schema_version") if isinstance(data, dict) else None
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise UnsupportedSchemaVersion(
                f"graph schema v{version} is not supported (supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)})")
        try:
            symbols = {
                q: Symbol(q, s["kind"], s["module"], s["file"], s["line"], s.get("parent"))
                for q, s in data["symbols"].items()
            }
            imports: dict[str, dict[str, ImportEdge]] = defaultdict(dict)
            for importer, targets in data["imports"].items():
                for target, e in targets.items():
                    imports[importer][target] = ImportEdge(set(e["symbols"]), e["wholesale"], e["line"])
            calls = [CallSite(c["caller"], c["target"], c["file"], c["line"]) for c in data["calls"]]
            return cls(data.get("repo", ""), data.get("sha", ""), set(data["modules"]), symbols, imports, calls)
        except (KeyError, TypeError, AttributeError) as exc:
            raise InvalidSnapshot(f"malformed graph JSON: {type(exc).__name__}: {exc}") from exc

    # ======================================================================
    # QUERIES
    # ======================================================================
    def resolve(self, name: str) -> Symbol:
        """Map a loose, human/LLM-supplied name to exactly one Symbol.

        Accepts a full qualname ("app.payment_client.PaymentClient.charge") or
        any unique dotted suffix ("PaymentClient.charge", "charge",
        "payment_client"), case-insensitively as a fallback. Zero or multiple
        matches raise ComponentError with suggestions, never a guess.
        """
        name = name.strip()
        if name in self.symbols:
            return self.symbols[name]
        for norm in (lambda s: s, str.lower):
            wanted = norm(name)
            hits = [s for q, s in self.symbols.items()
                    if norm(q) == wanted or norm(q).endswith("." + wanted)]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                options = sorted(h.qualname for h in hits)
                raise ComponentError(f"{name!r} is ambiguous; use a more specific name.", options[:10])
        close = difflib.get_close_matches(name, list(self.symbols), n=5, cutoff=0.4)
        raise ComponentError(f"No component named {name!r} in {self.repo or 'this repository'}.", close)

    def _members(self, symbol: Symbol) -> set[str]:
        """Everything whose change counts as a change to `symbol`."""
        if symbol.kind == "module":
            return {q for q, s in self.symbols.items() if s.module == symbol.qualname}
        if symbol.kind == "class":
            return {symbol.qualname} | {q for q, s in self.symbols.items() if s.parent == symbol.qualname}
        return {symbol.qualname}

    def _callers(self, targets: set[str], transitive: bool) -> list[dict]:
        """Callers of any of `targets`, breadth-first. Callers that are
        themselves inside `targets` (a class calling its own methods) are
        skipped: they are part of the change, not affected by it."""
        found: dict[str, dict] = {}
        frontier, depth = set(targets), 0
        while frontier:
            depth += 1
            next_frontier: set[str] = set()
            for target in frontier:
                for site in self._callers_by_target.get(target, []):
                    if site.caller in targets:
                        continue
                    entry = found.get(site.caller)
                    if entry is None:
                        caller = self.symbols[site.caller]
                        entry = found[site.caller] = {
                            "symbol": site.caller, "kind": caller.kind, "depth": depth,
                            "file": site.file, "call_sites": [],
                        }
                        next_frontier.add(site.caller)
                    if entry["depth"] == depth:
                        entry["call_sites"].append({"line": site.line, "calls": site.target})
            if not transitive:
                break
            frontier = next_frontier
        return sorted(found.values(), key=lambda e: (e["depth"], e["symbol"]))

    def _dependent_modules(self, symbol: Symbol, transitive: bool) -> list[dict]:
        """Modules that import the component's module, breadth-first through
        the reverse import graph. The FIRST hop is filtered to importers that
        actually pull in this symbol (or import the module wholesale); later
        hops follow any import, so they over-approximate — noted in output."""
        home = symbol.module
        top_name = symbol.qualname[len(home) + 1:].split(".")[0] if symbol.kind != "module" else None
        found: dict[str, dict] = {}
        frontier, depth = {home}, 0
        while frontier:
            depth += 1
            next_frontier: set[str] = set()
            for imported in frontier:
                for importer, edges in self.imports.items():
                    edge = edges.get(imported)
                    if edge is None or importer == home or importer in found:
                        continue
                    if depth == 1 and top_name and not (edge.wholesale or top_name in edge.symbols):
                        continue
                    found[importer] = {
                        "module": importer, "file": self.symbols[importer].file, "depth": depth,
                        "imports": "*" if edge.wholesale else sorted(edge.symbols),
                        "line": edge.line,
                    }
                    next_frontier.add(importer)
            if not transitive:
                break
            frontier = next_frontier
        return sorted(found.values(), key=lambda e: (e["depth"], e["module"]))

    def get_dependents(self, component: str, transitive: bool = True) -> dict:
        symbol = self.resolve(component)
        return {
            "component": symbol.qualname, "kind": symbol.kind, "defined_in": symbol.location,
            "dependent_modules": self._dependent_modules(symbol, transitive),
            "affected_symbols": self._callers(self._members(symbol), transitive),
            "notes": ("Static analysis. dependent_modules: depth 1 = imports this component; "
                      "deeper hops follow any import of the previous module (over-approximate). "
                      "affected_symbols: functions that call into the component, with line numbers."),
        }

    def get_callers(self, function: str, transitive: bool = False) -> dict:
        symbol = self.resolve(function)
        return {
            "function": symbol.qualname, "kind": symbol.kind, "defined_in": symbol.location,
            "callers": self._callers(self._members(symbol), transitive),
            "notes": ("Static analysis. depth 1 = direct callers. For a class, includes callers "
                      "of its constructor and any of its methods. Unresolvable dynamic calls "
                      "are not listed."),
        }

    def list_components(self) -> dict:
        modules = []
        for module in sorted(self.modules):
            members = [s for s in self.symbols.values() if s.module == module and s.kind != "module"]
            modules.append({
                "module": module,
                "file": self.symbols[module].file,
                "classes": {
                    c.qualname.rsplit(".", 1)[1]: sorted(
                        m.qualname.rsplit(".", 1)[1] for m in members if m.parent == c.qualname)
                    for c in members if c.kind == "class"
                },
                "functions": sorted(f.qualname.rsplit(".", 1)[1] for f in members
                                    if f.kind == "function" and f.parent is None),
            })
        return {"repo": self.repo, "sha": self.sha, "modules": modules}
