"""Source collection and the Python AST extractor, against the fixture tree."""

from __future__ import annotations

import json
import pathlib
import tempfile

from appmind_indexer.extract.files import MAX_FILE_BYTES, SourceFile, collect_python_files
from appmind_indexer.extract.python_ast import (
    EXTRACTOR_VERSION,
    SCHEMA_VERSION,
    build_graph_json,
    module_name,
)
from appmind_indexer.globs import matches_any
from tests.helpers import FIXTURE, Checker


def _graph(root=FIXTURE, **kwargs):
    files, skipped = collect_python_files(root, **kwargs)
    return files, skipped, build_graph_json(files, repo="o/r", sha="a" * 40)


def main() -> int:
    check = Checker()

    check.section("globs")
    check("** matches a nested directory", matches_any("a/tests/x.py", ["**/tests/**"]))
    check("** matches a top-level directory", matches_any("tests/x.py", ["**/tests/**"]))
    check("does not match a similarly named directory", not matches_any("src/contest/x.py", ["**/tests/**"]))
    check("* does not cross a slash", not matches_any("a/b.py", ["*.py"]))
    check("* matches within a segment", matches_any("b.py", ["*.py"]))

    check.section("module_name")
    check("plain module", module_name("app/payment_client.py") == "app.payment_client")
    check("__init__ collapses to the package", module_name("app/__init__.py") == "app")

    check.section("fixture tree: files and graph")
    files, skipped, ex = _graph()
    g = ex.graph
    check("collects the 6 fixture files", [f.path for f in files] == [
        "app/api.py", "app/inventory_client.py", "app/models.py",
        "app/notification_service.py", "app/order_service.py", "app/payment_client.py"])
    check("nothing skipped", not skipped and not ex.skipped)
    check("schema/extractor versions recorded",
          (g["schema_version"], g["extractor_version"]) == (SCHEMA_VERSION, EXTRACTOR_VERSION))
    check("repo and sha recorded", (g["repo"], g["sha"]) == ("o/r", "a" * 40))
    check("modules listed", "app.payment_client" in g["modules"] and len(g["modules"]) == 6)
    sym = g["symbols"]["app.payment_client.PaymentClient"]
    check("class symbol has kind, module, file, line",
          (sym["kind"], sym["module"], sym["file"], sym["parent"]) == ("class", "app.payment_client", "app/payment_client.py", None)
          and isinstance(sym["line"], int))
    method = g["symbols"]["app.payment_client.PaymentClient.charge"]
    check("method symbol has its class as parent", method["parent"] == "app.payment_client.PaymentClient")
    edge = g["imports"]["app.order_service"]["app.payment_client"]
    check("import edge records the imported names", "PaymentClient" in edge["symbols"])
    calls = {(c["caller"], c["target"]) for c in g["calls"]}
    check("resolves OrderService.place_order -> PaymentClient.charge",
          ("app.order_service.OrderService.place_order", "app.payment_client.PaymentClient.charge") in calls)
    check("stats match the graph",
          ex.stats["symbols"] == len(g["symbols"]) and ex.stats["call_edges"] == len(g["calls"]))
    check("graph is JSON-serializable", bool(json.dumps(g)))

    check.section("determinism")
    _, _, ex2 = _graph()
    check("same input gives byte-identical JSON",
          json.dumps(g, sort_keys=True) == json.dumps(ex2.graph, sort_keys=True))

    check.section("source_root prefix")
    pfiles, _, pex = _graph(source_prefix="src")
    check("repo-relative paths carry the prefix", pfiles[0].path.startswith("src/app/"))
    check("module names do not", "app.payment_client" in pex.graph["modules"])
    check("graph file paths carry the prefix",
          pex.graph["symbols"]["app.payment_client.PaymentClient"]["file"] == "src/app/payment_client.py")

    check.section("exclusions")
    efiles, _, _ = _graph(exclude=("**/api.py",))
    check("explicit exclude removes the file", "app/api.py" not in [f.path for f in efiles])
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        for rel in (".venv/lib/a.py", "node_modules/b.py", "site-packages/c.py", "pkg/ok.py"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("x = 1\n", encoding="utf-8")
        got = [f.path for f in collect_python_files(root)[0]]
        check("default excludes skip .venv / node_modules / site-packages", got == ["pkg/ok.py"], str(got))

    check.section("files that cannot be indexed are skipped, not fatal")
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "good.py").write_text("x = 1\n", encoding="utf-8")
        (root / "big.py").write_text("x = 1\n" * (MAX_FILE_BYTES // 5), encoding="utf-8")
        (root / "latin.py").write_bytes(b"x = '\xff\xfe'\n")
        (root / "nul.py").write_text("x = 1\x00\n", encoding="utf-8")
        files, skipped = collect_python_files(root)
        reasons = {s["path"]: s["reason"] for s in skipped}
        check("good file kept", [f.path for f in files] == ["good.py"])
        check("oversized skipped", "larger than" in reasons.get("big.py", ""))
        check("non-UTF-8 skipped", "UTF-8" in reasons.get("latin.py", ""))
        check("NUL byte skipped", "NUL" in reasons.get("nul.py", ""))
    broken = [SourceFile("bad.py", "bad.py", "python", 12, "def broken(:\n"),
              SourceFile("ok.py", "ok.py", "python", 6, "x = 1\n")]
    result = build_graph_json(broken, repo="o/r", sha="b" * 40)
    check("a syntax error is skipped and reported, the rest still parse",
          result.stats["files_parsed"] == 1 and result.skipped[0]["path"] == "bad.py"
          and result.skipped[0]["reason"].startswith("SyntaxError"))
    return check.finish()


if __name__ == "__main__":
    raise SystemExit(main())
