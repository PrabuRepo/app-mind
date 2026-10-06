"""
code_context/snapshots.py — READ-ONLY access to the code knowledge store.

Every function here only runs SELECT. The schema belongs to the indexer
(indexer/CONTRACT.md); this module never creates or alters a table, and treats
"the tables don't exist yet" as simply "no snapshot".

Failures are raised as CodeContextError subclasses so the retrieval path (which
must never crash) can catch one type and record an honest, specific message.

Snapshots are immutable, so anything derived from one is cached forever, keyed
by its id: the exported graph file on disk and the rebuilt CodeGraph in memory.
"""

from __future__ import annotations

import functools
import json
import os
import pathlib
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime

import psycopg
from dotenv import load_dotenv

from code_context.contract import (
    SUPPORTED_SCHEMA_VERSIONS,
    IndexUnavailable,
    NoSnapshot,
    UnsupportedSchemaVersion,
)
from app_profile.registry import select_profile
from code_context.graph import CodeGraph

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT_CACHE_DIR = PROJECT_ROOT / ".cache" / "snapshots"

_META_COLUMNS = "s.id, s.repo, s.ref, s.sha, s.source_root, s.extractor_version, s.schema_version, s.indexed_at, s.pinned"
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass(frozen=True)
class SnapshotMeta:
    id: str
    repo: str
    ref: str
    sha: str
    source_root: str
    extractor_version: str
    schema_version: int
    indexed_at: datetime
    pinned: bool


@dataclass(frozen=True)
class CodeFile:
    path: str
    content: str
    language: str | None


@functools.lru_cache(maxsize=1)
def _dsn() -> str:
    load_dotenv()
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB", "appmind")
    user = os.environ.get("POSTGRES_USER", "appmind")
    password = os.environ.get("POSTGRES_PASSWORD", "appmind")
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


def _connect() -> psycopg.Connection:
    return psycopg.connect(_dsn(), connect_timeout=5)


def _query(sql: str, params: tuple = ()) -> list[tuple]:
    """Run one SELECT and return all rows, translating database failures into
    this package's error types."""
    try:
        with _connect() as conn:
            return conn.execute(sql, params).fetchall()
    except psycopg.errors.UndefinedTable as exc:
        raise NoSnapshot("the code index has not been built yet (snapshot tables do not exist); "
                         "run the indexer") from exc
    except psycopg.Error as exc:
        raise IndexUnavailable(f"database error: {type(exc).__name__}: {str(exc)[:200]}") from exc


def _meta(row: tuple) -> SnapshotMeta:
    meta = SnapshotMeta(str(row[0]), *row[1:])
    if meta.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersion(
            f"snapshot {meta.repo}@{meta.sha[:7]} uses graph schema v{meta.schema_version}; "
            f"this AppMind supports {sorted(SUPPORTED_SCHEMA_VERSIONS)}")
    return meta


def target_repo() -> str:
    """Which repository questions are about: APPMIND_CODE_REPO if set (an
    override), else the first code repository in the application profile.
    (Phase 2 resolves this per question instead.)"""
    load_dotenv()
    configured = os.environ.get("APPMIND_CODE_REPO")
    if configured:
        return configured
    return select_profile().sources.code[0].repo


def get_head(repo: str | None = None) -> SnapshotMeta:
    """The current snapshot for `repo` (default: target_repo())."""
    repo = repo or target_repo()
    rows = _query(
        f"SELECT {_META_COLUMNS} FROM code_heads h JOIN code_snapshots s ON s.id = h.snapshot_id "
        "WHERE h.repo = %s", (repo,))
    if not rows:
        raise NoSnapshot(f"no code snapshot for {repo}; run the indexer")
    return _meta(rows[0])


def get_snapshot_for_sha(repo: str, sha: str) -> SnapshotMeta:
    """The newest snapshot of `repo` at commit `sha` (a full SHA or a 7+ char prefix)."""
    sha = sha.strip().lower()
    if not _SHA_RE.match(sha):
        raise ValueError(f"not a commit SHA or prefix: {sha!r}")
    rows = _query(
        f"SELECT {_META_COLUMNS} FROM code_snapshots s WHERE s.repo = %s AND s.sha LIKE %s "
        "ORDER BY s.indexed_at DESC LIMIT 1", (repo, sha + "%"))
    if not rows:
        raise NoSnapshot(f"no code snapshot for {repo} at {sha[:7]}; run the indexer (it may have been pruned)")
    return _meta(rows[0])


def resolve_snapshot(repo: str | None = None, pin: str | None = None) -> SnapshotMeta:
    """`pin` is a commit SHA (exact version, used by evals) or None / 'head'
    for the current snapshot."""
    repo = repo or target_repo()
    if pin and pin.lower() != "head":
        return get_snapshot_for_sha(repo, pin)
    return get_head(repo)


def get_files(snapshot_id: str, paths: list[str]) -> list[CodeFile]:
    """The stored text of `paths` in this snapshot, in the order requested.
    Paths the snapshot does not hold (skipped at index time) are omitted."""
    if not paths:
        return []
    rows = _query(
        "SELECT path, content, language FROM code_files WHERE snapshot_id = %s AND path = ANY(%s)",
        (snapshot_id, list(paths)))
    by_path = {r[0]: CodeFile(r[0], r[1], r[2]) for r in rows}
    return [by_path[p] for p in paths if p in by_path]


def _graph_json(snapshot_id: str) -> dict:
    rows = _query("SELECT graph FROM code_snapshots WHERE id = %s", (snapshot_id,))
    if not rows:
        raise NoSnapshot(f"snapshot {snapshot_id} no longer exists (it may have been pruned)")
    return rows[0][0]


def _is_valid_graph_file(path: pathlib.Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and "schema_version" in data and "symbols" in data


def export_graph_file(meta: SnapshotMeta) -> pathlib.Path:
    """Write the snapshot's graph JSON to .cache/snapshots/<id>.json (once; ids
    are immutable) and return the path. A missing or corrupt cached file is
    rewritten. The AST MCP server loads this file instead of talking to the
    database, so it never needs database credentials."""
    path = SNAPSHOT_CACHE_DIR / f"{meta.id}.json"
    if path.exists() and _is_valid_graph_file(path):
        return path
    graph = _graph_json(meta.id)
    SNAPSHOT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SNAPSHOT_CACHE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(graph, f)
        os.replace(tmp, path)   # atomic: a reader never sees a half-written file
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise
    return path


@functools.lru_cache(maxsize=8)
def load_graph(snapshot_id: str) -> CodeGraph:
    """The rebuilt CodeGraph for a snapshot (in-process, used by the eval
    harness for ground truth). Cached per id: snapshots never change."""
    return CodeGraph.from_dict(_graph_json(snapshot_id))
