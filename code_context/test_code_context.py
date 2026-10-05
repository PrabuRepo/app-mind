"""
code_context/test_code_context.py — the graph model and read-only snapshot
access.

    python -m code_context.test_code_context

The graph checks use code_context/fixtures/orderflow_graph.json, a snapshot
produced by the indexer's extractor (indexer/CONTRACT.md, schema v1). The
snapshot checks run against the real Postgres container (no mocked database,
per project convention) using throwaway rows inserted with plain SQL — this
test deliberately never imports the indexer — and delete them afterwards.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import uuid
from unittest.mock import patch

import psycopg
from psycopg.types.json import Jsonb

from code_context import snapshots
from code_context.contract import (
    IndexUnavailable,
    InvalidSnapshot,
    NoSnapshot,
    UnsupportedSchemaVersion,
)
from code_context.graph import CodeGraph, ComponentError

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "orderflow_graph.json"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def raises(exc_type, fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
    except exc_type:
        return True
    return False


def test_graph(data: dict) -> None:
    print("== CodeGraph: rebuilt from the contract's graph JSON ==")
    g = CodeGraph.from_dict(data)
    check("repo and sha carried over", (g.repo, g.sha) == (data["repo"], data["sha"]))
    check("all 29 symbols rebuilt", len(g.symbols) == 29, str(len(g.symbols)))
    deps = g.get_dependents("PaymentClient")
    mods = {m["module"]: m["depth"] for m in deps["dependent_modules"]}
    check("get_dependents: order_service at depth 1, api at depth 2",
          mods.get("app.order_service") == 1 and mods.get("app.api") == 2, str(mods))
    check("get_dependents: defined_in is file:line", deps["defined_in"] == "app/payment_client.py:22", deps["defined_in"])
    callers = g.get_callers("PaymentClient.charge")["callers"]
    check("get_callers: place_order is the only direct caller",
          [c["symbol"] for c in callers] == ["app.order_service.OrderService.place_order"])
    listing = g.list_components()
    check("list_components names the repo and sha", (listing["repo"], listing["sha"]) == (g.repo, g.sha))
    check("list_components lists the 6 modules", len(listing["modules"]) == 6)
    try:
        g.resolve("PaymentClent")
        suggestions = []
    except ComponentError as exc:
        suggestions = exc.suggestions
    check("an unknown name raises ComponentError with a helpful suggestion",
          any("PaymentClient" in s for s in suggestions), str(suggestions))
    check("an ambiguous name is refused, not guessed", raises(ComponentError, g.resolve, "__init__"))

    print("\n== CodeGraph.from_dict refuses what it cannot trust ==")
    bad_version = copy.deepcopy(data)
    bad_version["schema_version"] = 99
    check("unsupported schema_version is refused", raises(UnsupportedSchemaVersion, CodeGraph.from_dict, bad_version))
    check("a non-dict is refused", raises(UnsupportedSchemaVersion, CodeGraph.from_dict, None))
    missing = {k: v for k, v in data.items() if k != "calls"}
    check("a graph missing required fields is InvalidSnapshot", raises(InvalidSnapshot, CodeGraph.from_dict, missing))


def _tables_exist(conn) -> bool:
    return conn.execute("SELECT to_regclass('code_snapshots') IS NOT NULL").fetchone()[0]


def _insert(conn, repo: str, graph: dict, schema_version: int = 1, files: dict | None = None) -> str:
    snap_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO code_snapshots (id, repo, ref, sha, source_root, extractor_version, schema_version, graph, stats) "
        "VALUES (%s, %s, 'main', %s, '.', 'ast-1', %s, %s, %s)",
        (snap_id, repo, "a" * 40, schema_version, Jsonb(graph), Jsonb({})))
    for path, content in (files or {}).items():
        conn.execute(
            "INSERT INTO code_files (snapshot_id, path, language, size_bytes, content) VALUES (%s, %s, 'python', %s, %s)",
            (snap_id, path, len(content), content))
    conn.execute("INSERT INTO code_heads (repo, snapshot_id) VALUES (%s, %s)", (repo, snap_id))
    conn.commit()
    return snap_id


def test_snapshots(data: dict) -> None:
    print("\n== read-only snapshot access (real Postgres) ==")
    repo, bad_repo = f"test/ctx-{uuid.uuid4().hex[:8]}", f"test/ctx-{uuid.uuid4().hex[:8]}"
    cache_files: list[pathlib.Path] = []
    with snapshots._connect() as conn:
        if not _tables_exist(conn):
            print("  SKIP  snapshot tables do not exist (the indexer has not run); "
                  "checking the missing-table behavior only")
        else:
            try:
                snap_id = _insert(conn, repo, data, files={"app/a.py": "a = 1\n", "app/b.py": "b = 2\n"})
                bad_id = _insert(conn, bad_repo, data, schema_version=99)
                cache_files += [snapshots.SNAPSHOT_CACHE_DIR / f"{snap_id}.json"]

                meta = snapshots.get_head(repo)
                check("get_head returns the current snapshot",
                      (meta.id, meta.repo, meta.sha, meta.schema_version) == (snap_id, repo, "a" * 40, 1))
                check("get_head raises NoSnapshot for a repo that was never indexed",
                      raises(NoSnapshot, snapshots.get_head, "test/never-indexed"))
                check("get_head refuses a snapshot with an unsupported schema version",
                      raises(UnsupportedSchemaVersion, snapshots.get_head, bad_repo))
                check("a snapshot is found by commit SHA prefix",
                      snapshots.get_snapshot_for_sha(repo, "aaaaaaa").id == snap_id)
                check("an unknown SHA raises NoSnapshot", raises(NoSnapshot, snapshots.get_snapshot_for_sha, repo, "b" * 40))
                check("a malformed SHA is rejected outright", raises(ValueError, snapshots.get_snapshot_for_sha, repo, "x%"))
                check("resolve_snapshot('head') is the head",
                      snapshots.resolve_snapshot(repo, pin="head").id == snap_id)
                check("resolve_snapshot(<sha>) pins an exact version",
                      snapshots.resolve_snapshot(repo, pin="a" * 40).id == snap_id)

                files = snapshots.get_files(snap_id, ["app/b.py", "app/a.py", "app/missing.py"])
                check("get_files returns files in the order requested, omitting absent ones",
                      [f.path for f in files] == ["app/b.py", "app/a.py"])
                check("file text is exact", files[0].content == "b = 2\n")
                check("get_files with no paths is empty and needs no query", snapshots.get_files(snap_id, []) == [])

                path = snapshots.export_graph_file(meta)
                check("export_graph_file writes the graph JSON", json.loads(path.read_text(encoding="utf-8")) == data)
                with patch.object(snapshots, "_graph_json", side_effect=AssertionError("must not hit the database")):
                    check("a second export reuses the cached file (no database access)",
                          snapshots.export_graph_file(meta) == path)
                path.write_text("{ not json", encoding="utf-8")
                check("a corrupt cached file is rewritten from the database",
                      json.loads(snapshots.export_graph_file(meta).read_text(encoding="utf-8")) == data)

                snapshots.load_graph.cache_clear()
                g1, g2 = snapshots.load_graph(snap_id), snapshots.load_graph(snap_id)
                check("load_graph rebuilds a working CodeGraph",
                      "app.order_service" in {m["module"] for m in g1.get_dependents("PaymentClient")["dependent_modules"]})
                check("load_graph is cached per snapshot id", g1 is g2)
            finally:
                conn.rollback()
                for r in (repo, bad_repo):
                    conn.execute("DELETE FROM code_heads WHERE repo = %s", (r,))
                    conn.execute("DELETE FROM code_snapshots WHERE repo = %s", (r,))
                conn.commit()
                for p in cache_files:
                    p.unlink(missing_ok=True)

    print("\n== failure modes ==")

    class _NoTables:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a, **k): raise psycopg.errors.UndefinedTable("relation \"code_heads\" does not exist")

    with patch.object(snapshots, "_connect", lambda: _NoTables()):
        check("missing tables mean 'no snapshot yet', not a crash", raises(NoSnapshot, snapshots.get_head, "o/r"))
    with patch.object(snapshots, "_connect", side_effect=psycopg.OperationalError("connection refused")):
        check("an unreachable database is IndexUnavailable", raises(IndexUnavailable, snapshots.get_head, "o/r"))
    with patch.dict(os.environ, {"APPMIND_CODE_REPO": "configured/repo"}):
        check("APPMIND_CODE_REPO selects the target repo", snapshots.target_repo() == "configured/repo")


def main() -> int:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    test_graph(data)
    test_snapshots(data)
    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
