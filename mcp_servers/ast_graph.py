"""
mcp_servers/ast_graph.py — a static dependency + call graph of OrderFlow,
built by walking Python's own `ast` (abstract syntax tree) module.

WHY AST INSTEAD OF ASKING THE LLM:
"What depends on PaymentClient?" is a graph question with one correct
answer. If an LLM answers it by skimming files, it can miss a dependent or
invent one, and nothing tells you it did. An AST walk parses the code the
same way Python does, so the answer is a deterministic fact: same code in,
same graph out, no model, no network. That's the whole reason this is a
tool and not a prompt (and why code is not in the vector store).

TWO GRAPHS ARE BUILT:
  * import graph — module A imports module B (and which names from it)
  * call graph   — function F calls function G, resolved as far as static
                   analysis allows, with file:line so every edge is citable

KNOWN LIMITS (deliberate, not bugs — say so in the docs):
  * Best-effort static resolution. Calls through variables whose type isn't
    visible in the code (e.g. a callback passed in at runtime), inheritance
    (no MRO lookup), and dynamic dispatch are not resolved.
  * Relative imports (`from . import x`) are ignored; OrderFlow uses
    absolute `app.*` imports throughout.
  * Calls to anything outside the analysed root (stdlib, FastAPI) are
    dropped: this graph answers "what inside OrderFlow is affected".

This module has no dependency on the `mcp` SDK on purpose: it can be tested
and dumped to JSON on its own, and the SDK wrapper lives in ast_server.py.

    python -m mcp_servers.ast_graph            # dump the graph as JSON
"""

from __future__ import annotations

import ast
import difflib
import json
import pathlib
from collections import defaultdict
from dataclasses import dataclass, field

DEFAULT_ROOT = pathlib.Path(__file__).resolve().parent.parent / "orderflow-app"


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
    file: str                # path relative to root, posix style
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
    def __init__(self, root: pathlib.Path, modules: set[str]):
        self.root = root
        self.modules = modules
        self.symbols: dict[str, Symbol] = {}
        # importer module -> imported module -> ImportEdge
        self.imports: dict[str, dict[str, ImportEdge]] = defaultdict(dict)
        self.call_sites: list[CallSite] = []
        self._callers_by_target: dict[str, list[CallSite]] = defaultdict(list)
        # Name-binding tables used only while resolving calls (see _index_types):
        #   module -> local name -> qualname it refers to (import or same-module def)
        self._bindings: dict[str, dict[str, str]] = defaultdict(dict)
        #   module -> module-level variable -> class qualname (`svc = OrderService()`)
        self._var_types: dict[str, dict[str, str]] = defaultdict(dict)
        #   class qualname -> attribute -> class qualname (`self.pc = PaymentClient()`)
        self._attr_types: dict[str, dict[str, str]] = defaultdict(dict)

    # -- pass 1: what is defined where ------------------------------------
    def _index_definitions(self, module: str, file: str, tree: ast.Module) -> None:
        self.symbols[module] = Symbol(module, "module", module, file, 1)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                cls = f"{module}.{node.name}"
                self.symbols[cls] = Symbol(cls, "class", module, file, node.lineno)
                self._bindings[module][node.name] = cls
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        fn = f"{cls}.{item.name}"
                        self.symbols[fn] = Symbol(fn, "function", module, file, item.lineno, parent=cls)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = f"{module}.{node.name}"
                self.symbols[fn] = Symbol(fn, "function", module, file, node.lineno)
                self._bindings[module][node.name] = fn

    # -- pass 2: who imports whom -----------------------------------------
    def _index_imports(self, module: str, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level or not node.module:
                    continue  # relative import — out of scope, see module docstring
                for alias in node.names:
                    bound = alias.asname or alias.name
                    submodule = f"{node.module}.{alias.name}"
                    if submodule in self.modules:        # `from app import models`
                        self._add_import(module, submodule, None, node.lineno)
                        self._bindings[module][bound] = submodule
                    elif node.module in self.modules:    # `from app.models import Order`
                        self._add_import(module, node.module, alias.name, node.lineno)
                        qualname = f"{node.module}.{alias.name}"
                        if qualname in self.symbols:
                            self._bindings[module][bound] = qualname
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in self.modules:
                        self._add_import(module, alias.name, None, node.lineno)
                        if alias.asname:
                            self._bindings[module][alias.asname] = alias.name

    def _add_import(self, importer: str, imported: str, symbol: str | None, line: int) -> None:
        edge = self.imports[importer].setdefault(imported, ImportEdge(line=line))
        if symbol is None:
            edge.wholesale = True
        else:
            edge.symbols.add(symbol)

    # -- pass 3: what type is each variable/attribute ---------------------
    # A call like `self.payment_client.charge(...)` can only be resolved to
    # PaymentClient.charge if we know self.payment_client is a PaymentClient.
    # We learn that from the simplest possible evidence: `x = SomeClass(...)`.
    def _kind(self, qualname: str | None) -> str | None:
        symbol = self.symbols.get(qualname) if qualname else None
        return symbol.kind if symbol else None

    def _class_of_call(self, module: str, value: ast.expr | None) -> str | None:
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            target = self._bindings[module].get(value.func.id)
            if self._kind(target) == "class":
                return target
        return None

    def _index_types(self, module: str, tree: ast.Module) -> None:
        for node in tree.body:
            if isinstance(node, ast.Assign):
                cls = self._class_of_call(module, node.value)
                for target in node.targets:
                    if cls and isinstance(target, ast.Name):
                        self._var_types[module][target.id] = cls
            elif isinstance(node, ast.ClassDef):
                owner = f"{module}.{node.name}"
                for method in node.body:
                    if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    for stmt in ast.walk(method):
                        if not isinstance(stmt, ast.Assign):
                            continue
                        cls = self._class_of_call(module, stmt.value)
                        for target in stmt.targets:
                            if (cls and isinstance(target, ast.Attribute)
                                    and isinstance(target.value, ast.Name) and target.value.id == "self"):
                                self._attr_types[owner][target.attr] = cls

    # -- pass 4: who calls whom -------------------------------------------
    def _local_types(self, module: str, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
        """Variables inside one function whose class we can see: annotated
        parameters (`client: PaymentClient`) and `x = SomeClass(...)`."""
        types: dict[str, str] = {}
        for arg in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]:
            if isinstance(arg.annotation, ast.Name):
                target = self._bindings[module].get(arg.annotation.id)
                if self._kind(target) == "class":
                    types[arg.arg] = target
        for stmt in ast.walk(fn):
            if isinstance(stmt, ast.Assign):
                cls = self._class_of_call(module, stmt.value)
                for target in stmt.targets:
                    if cls and isinstance(target, ast.Name):
                        types[target.id] = cls
        return types

    def _owner_of(self, expr: ast.expr, module: str, cls: str | None,
                  local_types: dict[str, str]) -> str | None:
        """Qualname of the class or module that `expr` refers to, if visible."""
        if isinstance(expr, ast.Name):
            if expr.id == "self" and cls:
                return cls
            for table in (local_types, self._var_types[module]):
                if expr.id in table:
                    return table[expr.id]
            bound = self._bindings[module].get(expr.id)
            if self._kind(bound) in ("class", "module"):
                return bound
        elif (isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name)
              and expr.value.id == "self" and cls):
            return self._attr_types[cls].get(expr.attr)   # self.<attr>.method()
        return None

    def _resolve_call(self, func: ast.expr, module: str, cls: str | None,
                      local_types: dict[str, str]) -> str | None:
        if isinstance(func, ast.Name):
            target = self._bindings[module].get(func.id)
            kind = self._kind(target)
            if kind == "function":
                return target
            if kind == "class":  # constructor call: prefer an explicit __init__
                init = f"{target}.__init__"
                return init if init in self.symbols else target
            return None
        if isinstance(func, ast.Attribute):
            owner = self._owner_of(func.value, module, cls, local_types)
            candidate = f"{owner}.{func.attr}" if owner else None
            return candidate if candidate in self.symbols else None
        return None

    def _record_calls(self, caller: str, nodes: list[ast.AST], module: str, file: str,
                      cls: str | None, local_types: dict[str, str]) -> None:
        for root in nodes:
            for node in ast.walk(root):
                if not isinstance(node, ast.Call):
                    continue
                target = self._resolve_call(node.func, module, cls, local_types)
                if target:
                    site = CallSite(caller, target, file, node.lineno)
                    self.call_sites.append(site)
                    self._callers_by_target[target].append(site)

    def _index_calls(self, module: str, file: str, tree: ast.Module) -> None:
        module_level: list[ast.AST] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                cls = f"{module}.{node.name}"
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._record_calls(f"{cls}.{item.name}", [item], module, file, cls,
                                           self._local_types(module, item))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._record_calls(f"{module}.{node.name}", [node], module, file, None,
                                   self._local_types(module, node))
            elif not isinstance(node, (ast.Import, ast.ImportFrom)):
                module_level.append(node)   # e.g. `order_service = OrderService()`
        self._record_calls(module, module_level, module, file, None, {})

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
        raise ComponentError(f"No component named {name!r} in the OrderFlow code.", close)

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
        return {"root": self.root.name, "modules": modules}

    def to_dict(self) -> dict:
        """The whole static graph as plain JSON — the 'offline artifact' view."""
        return {
            "symbols": {q: {"kind": s.kind, "location": s.location, "parent": s.parent}
                        for q, s in sorted(self.symbols.items())},
            "imports": {imp: {tgt: {"symbols": sorted(e.symbols), "wholesale": e.wholesale, "line": e.line}
                              for tgt, e in sorted(edges.items())}
                        for imp, edges in sorted(self.imports.items())},
            "calls": [{"caller": c.caller, "target": c.target, "location": f"{c.file}:{c.line}"}
                      for c in self.call_sites],
        }


def _module_name(root: pathlib.Path, path: pathlib.Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def build_graph(root: pathlib.Path | str = DEFAULT_ROOT) -> CodeGraph:
    """Parse every .py file under `root` and build the graph. Cheap enough
    (OrderFlow is a handful of small files) to do at every server start, which
    also means the graph can never be stale relative to the code on disk."""
    root = pathlib.Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"AST root does not exist: {root}")
    parsed: dict[str, tuple[str, ast.Module]] = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        # Explicit utf-8: Windows defaults to cp1252 (see FAILURES.md #3).
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parsed[_module_name(root, path)] = (path.relative_to(root).as_posix(), tree)

    graph = CodeGraph(root, set(parsed))
    for module, (file, tree) in parsed.items():
        graph._index_definitions(module, file, tree)
    for module, (_, tree) in parsed.items():
        graph._index_imports(module, tree)
    for module, (_, tree) in parsed.items():
        graph._index_types(module, tree)
    for module, (file, tree) in parsed.items():
        graph._index_calls(module, file, tree)
    return graph


if __name__ == "__main__":
    print(json.dumps(build_graph().to_dict(), indent=2))
