"""
appmind_indexer/extract/python_ast.py — builds a static dependency + call
graph of a Python codebase with the standard-library `ast` module, and
serializes it as the contract's graph JSON (see CONTRACT.md, schema v1).

This is EXTRACTION only. It never answers questions about the graph; that is
the consumer's job (AppMind's code_context package). Keeping the two apart is
what lets this project live in its own repository.

FOUR PASSES (each depends on the one before it):
  1. definitions — what is defined where (modules, classes, functions)
  2. imports     — which module imports which, and which names from it
  3. types       — what class a variable/attribute holds (`x = SomeClass()`)
  4. calls       — which function calls which, with file:line per call

KNOWN LIMITS (deliberate, documented in CONTRACT.md):
  * Best-effort static resolution: calls through variables whose type isn't
    visible in the code, inheritance (no MRO lookup), and dynamic dispatch
    are not resolved.
  * Relative imports (`from . import x`) are ignored; code is expected to use
    absolute imports rooted at the source root.
  * Calls to anything outside the analysed source root are dropped.

Pure function of its input: no I/O, no network, no clock. Same files in, same
graph out.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field

from appmind_indexer.extract.files import SourceFile

SCHEMA_VERSION = 1
EXTRACTOR_VERSION = "ast-1"


@dataclass
class Symbol:
    qualname: str            # e.g. "app.payment_client.PaymentClient.charge"
    kind: str                # "module" | "class" | "function"
    module: str              # e.g. "app.payment_client"
    file: str                # repo-root-relative path, posix style
    line: int
    parent: str | None = None  # owning class qualname, for methods


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


@dataclass
class Extraction:
    graph: dict                      # the contract's graph JSON, schema v1
    skipped: list[dict]              # files that could not be parsed
    stats: dict


def module_name(rel_path: str) -> str:
    """'app/payment_client.py' -> 'app.payment_client'; 'app/__init__.py' -> 'app'."""
    stem = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    parts = stem.split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class _Extractor:
    def __init__(self, modules: set[str]):
        self.modules = modules
        self.symbols: dict[str, Symbol] = {}
        # importer module -> imported module -> ImportEdge
        self.imports: dict[str, dict[str, ImportEdge]] = defaultdict(dict)
        self.call_sites: list[CallSite] = []
        # Name-binding tables used only while resolving calls (see _index_types):
        #   module -> local name -> qualname it refers to (import or same-module def)
        self._bindings: dict[str, dict[str, str]] = defaultdict(dict)
        #   module -> module-level variable -> class qualname (`svc = OrderService()`)
        self._var_types: dict[str, dict[str, str]] = defaultdict(dict)
        #   class qualname -> attribute -> class qualname (`self.pc = PaymentClient()`)
        self._attr_types: dict[str, dict[str, str]] = defaultdict(dict)

    # -- pass 1: what is defined where ------------------------------------
    def index_definitions(self, module: str, file: str, tree: ast.Module) -> None:
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
    def index_imports(self, module: str, tree: ast.Module) -> None:
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

    def index_types(self, module: str, tree: ast.Module) -> None:
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
                    self.call_sites.append(CallSite(caller, target, file, node.lineno))

    def index_calls(self, module: str, file: str, tree: ast.Module) -> None:
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


def build_graph_json(files: list[SourceFile], *, repo: str, sha: str) -> Extraction:
    """Parse `files` and return the contract's graph JSON (schema v1).

    A file with a syntax error is skipped and reported, not fatal: one broken
    file must not block indexing the rest of a repository.
    """
    parsed: dict[str, tuple[str, ast.Module]] = {}
    skipped: list[dict] = []
    for f in sorted(files, key=lambda f: f.path):
        try:
            tree = ast.parse(f.content, filename=f.path)
        except SyntaxError as exc:
            skipped.append({"path": f.path, "reason": f"SyntaxError: {exc.msg} (line {exc.lineno})"})
            continue
        parsed[module_name(f.rel)] = (f.path, tree)

    ex = _Extractor(set(parsed))
    for module, (file, tree) in parsed.items():
        ex.index_definitions(module, file, tree)
    for module, (_, tree) in parsed.items():
        ex.index_imports(module, tree)
    for module, (_, tree) in parsed.items():
        ex.index_types(module, tree)
    for module, (file, tree) in parsed.items():
        ex.index_calls(module, file, tree)

    graph = {
        "schema_version": SCHEMA_VERSION,
        "repo": repo,
        "sha": sha,
        "extractor_version": EXTRACTOR_VERSION,
        "modules": sorted(parsed),
        "symbols": {
            q: {"kind": s.kind, "module": s.module, "file": s.file, "line": s.line, "parent": s.parent}
            for q, s in sorted(ex.symbols.items())
        },
        "imports": {
            importer: {
                target: {"symbols": sorted(e.symbols), "wholesale": e.wholesale, "line": e.line}
                for target, e in sorted(edges.items())
            }
            for importer, edges in sorted(ex.imports.items())
        },
        "calls": [
            {"caller": c.caller, "target": c.target, "file": c.file, "line": c.line}
            for c in ex.call_sites
        ],
    }
    stats = {
        "files_parsed": len(parsed),
        "files_skipped": len(skipped),
        "symbols": len(graph["symbols"]),
        "import_edges": sum(len(edges) for edges in graph["imports"].values()),
        "call_edges": len(graph["calls"]),
    }
    return Extraction(graph=graph, skipped=skipped, stats=stats)
