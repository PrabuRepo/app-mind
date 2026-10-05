"""
appmind_indexer/store.py — the schema and every WRITE to the knowledge store.

This module OWNS the database schema (see CONTRACT.md). AppMind only reads
these tables. Writes for one repository happen in a single transaction, so a
failed run never leaves a half-updated repo: the previous head keeps serving.

Unlike AppMind's query path, a batch indexer is allowed to fail loudly —
functions here raise, and run.py records the failure in `index_runs`.
"""

from __future__ import annotations

import uuid

import psycopg
from psycopg.types.json import Jsonb

from appmind_indexer import config

DDL = """
CREATE TABLE IF NOT EXISTS code_snapshots (
    id                UUID PRIMARY KEY,
    repo              TEXT NOT NULL,
    ref               TEXT NOT NULL,
    sha               TEXT NOT NULL,
    source_root       TEXT NOT NULL DEFAULT '.',
    extractor_version TEXT NOT NULL,
    schema_version    INTEGER NOT NULL,
    graph             JSONB NOT NULL,
    stats             JSONB NOT NULL,
    pinned            BOOLEAN NOT NULL DEFAULT false,
    indexed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repo, sha, extractor_version)
);

CREATE TABLE IF NOT EXISTS code_files (
    snapshot_id UUID NOT NULL REFERENCES code_snapshots(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    language    TEXT,
    size_bytes  INTEGER NOT NULL,
    content     TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, path)
);

CREATE TABLE IF NOT EXISTS code_heads (
    repo        TEXT PRIMARY KEY,
    snapshot_id UUID NOT NULL REFERENCES code_snapshots(id),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS index_runs (
    id          UUID PRIMARY KEY,
    repo        TEXT NOT NULL,
    sha         TEXT,
    trigger     TEXT NOT NULL,
    status      TEXT NOT NULL,
    error       TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
"""


def connect() -> psycopg.Connection:
    return psycopg.connect(config.postgres_dsn(), connect_timeout=5)


def ensure_schema(conn: psycopg.Connection) -> None:
    """Idempotent: CREATE TABLE IF NOT EXISTS for every contract table."""
    conn.execute(DDL)
    conn.commit()


# -- audit trail -----------------------------------------------------------
def start_run(conn: psycopg.Connection, repo: str, trigger: str) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO index_runs (id, repo, trigger, status) VALUES (%s, %s, %s, 'running')",
        (run_id, repo, trigger),
    )
    conn.commit()   # committed immediately so a later failure still leaves a record
    return run_id


def finish_run(conn: psycopg.Connection, run_id: str, status: str,
               sha: str | None = None, error: str | None = None) -> None:
    conn.execute(
        "UPDATE index_runs SET status = %s, sha = %s, error = %s, finished_at = now() WHERE id = %s",
        (status, sha, error, run_id),
    )
    conn.commit()


# -- snapshots -------------------------------------------------------------
def find_snapshot(conn: psycopg.Connection, repo: str, sha: str, extractor_version: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM code_snapshots WHERE repo = %s AND sha = %s AND extractor_version = %s",
        (repo, sha, extractor_version),
    ).fetchone()
    return str(row[0]) if row else None


def set_head(conn: psycopg.Connection, repo: str, snapshot_id: str) -> None:
    conn.execute(
        "INSERT INTO code_heads (repo, snapshot_id) VALUES (%s, %s) "
        "ON CONFLICT (repo) DO UPDATE SET snapshot_id = EXCLUDED.snapshot_id, updated_at = now()",
        (repo, snapshot_id),
    )


def write_snapshot(
    conn: psycopg.Connection,
    *,
    repo: str,
    ref: str,
    sha: str,
    source_root: str,
    extractor_version: str,
    schema_version: int,
    graph: dict,
    stats: dict,
    files,
    pinned: bool = False,
    replace_existing: bool = False,
) -> str:
    """Insert a snapshot with all its files and point the repo's head at it,
    all in ONE transaction (commits on success, rolls back on any error)."""
    snapshot_id = str(uuid.uuid4())
    with conn.transaction():
        if replace_existing:
            conn.execute(
                "DELETE FROM code_heads WHERE snapshot_id IN "
                "(SELECT id FROM code_snapshots WHERE repo = %s AND sha = %s AND extractor_version = %s)",
                (repo, sha, extractor_version),
            )
            conn.execute(
                "DELETE FROM code_snapshots WHERE repo = %s AND sha = %s AND extractor_version = %s",
                (repo, sha, extractor_version),
            )
        conn.execute(
            "INSERT INTO code_snapshots "
            "(id, repo, ref, sha, source_root, extractor_version, schema_version, graph, stats, pinned) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (snapshot_id, repo, ref, sha, source_root, extractor_version, schema_version,
             Jsonb(graph), Jsonb(stats), pinned),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO code_files (snapshot_id, path, language, size_bytes, content) "
                "VALUES (%s, %s, %s, %s, %s)",
                [(snapshot_id, f.path, f.language, f.size_bytes, f.content) for f in files],
            )
        set_head(conn, repo, snapshot_id)
    return snapshot_id


def prune(conn: psycopg.Connection, repo: str, keep: int) -> int:
    """Delete this repo's old snapshots, keeping the newest `keep`, the current
    head, and anything pinned. Returns how many were removed."""
    cur = conn.execute(
        "DELETE FROM code_snapshots WHERE repo = %s AND pinned = false "
        "AND id NOT IN (SELECT snapshot_id FROM code_heads WHERE repo = %s) "
        "AND id NOT IN (SELECT id FROM code_snapshots WHERE repo = %s ORDER BY indexed_at DESC LIMIT %s)",
        (repo, repo, repo, keep),
    )
    conn.commit()
    return cur.rowcount
