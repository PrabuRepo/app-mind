"""Orchestration (run.index_target) with the network replaced by the fixture
tree, against the real Postgres container. Covers success, skip-if-unchanged,
--force, and the failure paths that must leave the previous head serving."""

from __future__ import annotations

import uuid
from unittest.mock import patch

from appmind_indexer import fetch, run, store
from appmind_indexer.registry import Target
from tests.helpers import FIXTURE, Checker


def _head(conn, repo):
    row = conn.execute("SELECT snapshot_id FROM code_heads WHERE repo = %s", (repo,)).fetchone()
    return str(row[0]) if row else None


def _last_run(conn, repo):
    return conn.execute(
        "SELECT status, error FROM index_runs WHERE repo = %s ORDER BY started_at DESC LIMIT 1", (repo,)).fetchone()


def _index(conn, target, *, sha="1" * 40, force=False, pin=False, resolve_error=None):
    resolve = patch.object(fetch, "resolve_sha", return_value=sha, side_effect=resolve_error)
    download = patch.object(fetch, "download_tarball", return_value=FIXTURE)
    with resolve, download:
        return run.index_target(conn, target, token="t", force=force, pin=pin, trigger="cli")


def main() -> int:
    check = Checker()
    repo = f"test/indexer-{uuid.uuid4().hex[:8]}"
    target = Target(repo=repo, ref="main", source_root=".")

    with store.connect() as conn:
        store.ensure_schema(conn)
        try:
            check.section("first index of a commit")
            check("returns 'succeeded'", _index(conn, target) == "succeeded")
            head = _head(conn, repo)
            check("a head snapshot exists", head is not None)
            symbols, files = conn.execute(
                "SELECT (stats->>'symbols')::int, (SELECT count(*) FROM code_files WHERE snapshot_id = s.id) "
                "FROM code_snapshots s WHERE id = %s", (head,)).fetchone()
            check("29 symbols and 6 files were stored", (symbols, files) == (29, 6), f"{symbols}, {files}")
            check("the run is audited as succeeded", _last_run(conn, repo)[0] == "succeeded")

            check.section("same commit again")
            check("returns 'skipped'", _index(conn, target) == "skipped")
            check("the head is unchanged", _head(conn, repo) == head)
            check("the run is audited as skipped", _last_run(conn, repo)[0] == "skipped")

            check.section("--force")
            check("returns 'succeeded'", _index(conn, target, force=True) == "succeeded")
            forced = _head(conn, repo)
            check("a fresh snapshot replaced the old one", forced != head)
            count = conn.execute("SELECT count(*) FROM code_snapshots WHERE repo = %s", (repo,)).fetchone()[0]
            check("still exactly one snapshot for that commit", count == 1)

            check.section("--pin")
            check("returns 'succeeded'", _index(conn, target, sha="2" * 40, pin=True) == "succeeded")
            pinned = conn.execute(
                "SELECT pinned FROM code_snapshots WHERE repo = %s AND sha = %s", (repo, "2" * 40)).fetchone()[0]
            check("the new snapshot is pinned", pinned is True)
            pinned_head = _head(conn, repo)

            check.section("failures leave the previous head serving")
            status = _index(conn, target, resolve_error=fetch.FetchError("boom"))
            check("a fetch failure returns 'failed'", status == "failed")
            last = _last_run(conn, repo)
            check("the failure is audited with its message", last[0] == "failed" and "boom" in (last[1] or ""), str(last))
            check("the head is untouched", _head(conn, repo) == pinned_head)

            bad_root = Target(repo=repo, ref="main", source_root="does/not/exist")
            check("a source_root that is not a directory fails", _index(conn, bad_root, sha="3" * 40) == "failed")
            check("and the error says why", "not a directory" in (_last_run(conn, repo)[1] or ""))
            check("the head is still untouched", _head(conn, repo) == pinned_head)

            check.section("docs are accepted but not indexed yet")
            with_docs = Target(repo=repo, ref="main", source_root=".", docs=("README.md",))
            check("a target with docs still indexes", _index(conn, with_docs, sha="4" * 40) == "succeeded")
        finally:
            conn.rollback()
            conn.execute("DELETE FROM code_heads WHERE repo = %s", (repo,))
            conn.execute("DELETE FROM code_snapshots WHERE repo = %s", (repo,))
            conn.execute("DELETE FROM index_runs WHERE repo = %s", (repo,))
            conn.commit()
    return check.finish()


if __name__ == "__main__":
    raise SystemExit(main())
