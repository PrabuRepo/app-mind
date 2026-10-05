"""The store: schema, atomic snapshot writes, head pointer, pruning, audit.

Runs against the real Postgres container (same convention as the rest of the
project: no mocked databases). Every row it creates uses a throwaway repo name
and is deleted at the end.
"""

from __future__ import annotations

import uuid

from appmind_indexer import store
from appmind_indexer.extract.files import SourceFile
from tests.helpers import Checker

GRAPH = {"schema_version": 1, "symbols": {}, "imports": {}, "calls": [], "modules": []}


def _files(n: int = 2, bad: bool = False) -> list[SourceFile]:
    files = [SourceFile(f"app/f{i}.py", f"app/f{i}.py", "python", 6, f"x = {i}\n") for i in range(n)]
    if bad:
        files.append(SourceFile("app/bad.py", "app/bad.py", "python", 4, "a\x00b"))
    return files


def _write(conn, repo, sha, **kwargs) -> str:
    return store.write_snapshot(
        conn, repo=repo, ref="main", sha=sha, source_root=".", extractor_version="ast-1",
        schema_version=1, graph=GRAPH, stats={"files_parsed": 2}, files=kwargs.pop("files", _files()), **kwargs,
    )


def _head(conn, repo):
    row = conn.execute("SELECT snapshot_id FROM code_heads WHERE repo = %s", (repo,)).fetchone()
    return str(row[0]) if row else None


def _count(conn, repo) -> int:
    return conn.execute("SELECT count(*) FROM code_snapshots WHERE repo = %s", (repo,)).fetchone()[0]


def _cleanup(conn, repo) -> None:
    conn.rollback()
    conn.execute("DELETE FROM code_heads WHERE repo = %s", (repo,))
    conn.execute("DELETE FROM code_snapshots WHERE repo = %s", (repo,))
    conn.execute("DELETE FROM index_runs WHERE repo = %s", (repo,))
    conn.commit()


def main() -> int:
    check = Checker()
    repo = f"test/indexer-{uuid.uuid4().hex[:8]}"
    A, B, C, D = "a" * 40, "b" * 40, "c" * 40, "d" * 40

    with store.connect() as conn:
        try:
            check.section("schema")
            store.ensure_schema(conn)
            store.ensure_schema(conn)
            check("ensure_schema is idempotent", True)

            check.section("write, find, head")
            a_id = _write(conn, repo, A)
            check("find_snapshot returns the written snapshot", store.find_snapshot(conn, repo, A, "ast-1") == a_id)
            check("find_snapshot is None for an unknown sha", store.find_snapshot(conn, repo, B, "ast-1") is None)
            check("head points at the new snapshot", _head(conn, repo) == a_id)
            n_files = conn.execute("SELECT count(*) FROM code_files WHERE snapshot_id = %s", (a_id,)).fetchone()[0]
            check("every file was stored", n_files == 2)
            graph = conn.execute("SELECT graph FROM code_snapshots WHERE id = %s", (a_id,)).fetchone()[0]
            check("the graph JSON round-trips unchanged", graph == GRAPH)
            content = conn.execute(
                "SELECT content FROM code_files WHERE snapshot_id = %s AND path = 'app/f1.py'", (a_id,)).fetchone()[0]
            check("file text is stored verbatim", content == "x = 1\n")

            check.section("a second snapshot moves the head")
            b_id = _write(conn, repo, B)
            check("head moved to the newer snapshot", _head(conn, repo) == b_id)
            check("both snapshots exist", _count(conn, repo) == 2)

            check.section("pruning keeps the head, the newest N, and anything pinned")
            removed = store.prune(conn, repo, keep=1)
            check("the old, unpinned, non-head snapshot was pruned", removed == 1 and _count(conn, repo) == 1)
            c_id = _write(conn, repo, C, pinned=True)
            d_id = _write(conn, repo, D)
            store.prune(conn, repo, keep=1)
            survivors = {str(r[0]) for r in conn.execute("SELECT id FROM code_snapshots WHERE repo = %s", (repo,))}
            check("the pinned snapshot survives pruning", c_id in survivors)
            check("the head survives pruning", d_id in survivors)
            check("an older unpinned snapshot is gone", b_id not in survivors)

            check.section("a failed write rolls back completely")
            head_before, count_before = _head(conn, repo), _count(conn, repo)
            try:
                _write(conn, repo, "e" * 40, files=_files(bad=True))   # NUL byte: Postgres rejects it
                raised = False
            except Exception:
                raised = True
            check("the write raised", raised)
            check("no half-written snapshot remains", _count(conn, repo) == count_before)
            check("the head still points at the previous snapshot", _head(conn, repo) == head_before)

            check.section("re-indexing the same commit")
            try:
                _write(conn, repo, D)
                dup = False
            except Exception:
                dup = True
            check("a duplicate (repo, sha, extractor) is rejected without replace_existing", dup)
            check("and the rejected attempt left the head alone", _head(conn, repo) == head_before)
            new_id = _write(conn, repo, D, replace_existing=True)
            check("replace_existing swaps the snapshot", _head(conn, repo) == new_id and new_id != d_id)
            same_sha = conn.execute(
                "SELECT count(*) FROM code_snapshots WHERE repo = %s AND sha = %s", (repo, D)).fetchone()[0]
            check("exactly one snapshot remains for that commit", same_sha == 1)

            check.section("audit trail")
            run_id = store.start_run(conn, repo, "cli")
            status = conn.execute("SELECT status FROM index_runs WHERE id = %s", (run_id,)).fetchone()[0]
            check("start_run records 'running'", status == "running")
            store.finish_run(conn, run_id, "failed", sha=D, error="boom")
            row = conn.execute("SELECT status, error, sha, finished_at FROM index_runs WHERE id = %s",
                               (run_id,)).fetchone()
            check("finish_run records status, error, sha and a finish time",
                  row[0] == "failed" and row[1] == "boom" and row[2] == D and row[3] is not None)
        finally:
            _cleanup(conn, repo)
    return check.finish()


if __name__ == "__main__":
    raise SystemExit(main())
