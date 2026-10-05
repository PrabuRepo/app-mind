# Data contract

This document is the **only interface** between the indexer and its consumers
(today: AppMind's `code_context` package). Neither side imports the other's
code. They agree on the data below and on the versioning rules at the end.

If you change anything in this file, you are changing the contract: follow
"Versioning rules".

## Ownership

- The **indexer owns the schema and every write.** It creates the tables
  (`appmind_indexer/store.py`, `ensure_schema()`).
- **Consumers are read-only** (`SELECT` only) and must tolerate the tables not
  existing yet (the indexer has not run) as "no snapshot".

## 1. Postgres tables

```sql
CREATE TABLE IF NOT EXISTS code_snapshots (
    id                UUID PRIMARY KEY,
    repo              TEXT NOT NULL,              -- "owner/name"
    ref               TEXT NOT NULL,              -- branch/tag that was requested
    sha               TEXT NOT NULL,              -- resolved commit: the pin
    source_root       TEXT NOT NULL DEFAULT '.',  -- directory inside the repo that was analysed
    extractor_version TEXT NOT NULL,              -- e.g. "ast-1"
    schema_version    INTEGER NOT NULL,           -- version of the graph JSON (section 2)
    graph             JSONB NOT NULL,             -- the graph JSON
    stats             JSONB NOT NULL,             -- counts, plus skipped_files [{path, reason}]
    pinned            BOOLEAN NOT NULL DEFAULT false,   -- never pruned (used to pin eval snapshots)
    indexed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repo, sha, extractor_version)
);

CREATE TABLE IF NOT EXISTS code_files (
    snapshot_id UUID NOT NULL REFERENCES code_snapshots(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,                    -- repo-root-relative, POSIX separators
    language    TEXT,
    size_bytes  INTEGER NOT NULL,
    content     TEXT NOT NULL,                    -- the file's exact UTF-8 text, never normalized
    PRIMARY KEY (snapshot_id, path)
);

CREATE TABLE IF NOT EXISTS code_heads (
    repo        TEXT PRIMARY KEY,                 -- the CURRENT snapshot for each repo
    snapshot_id UUID NOT NULL REFERENCES code_snapshots(id),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS index_runs (            -- audit trail; consumers rarely need it
    id          UUID PRIMARY KEY,
    repo        TEXT NOT NULL,
    sha         TEXT,
    trigger     TEXT NOT NULL,                    -- cli | compose | webhook | schedule
    status      TEXT NOT NULL,                    -- running | succeeded | skipped | failed
    error       TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
```

Guarantees:

- **Atomic per repo.** A snapshot, its files and the head pointer are written
  in one transaction. A consumer never sees a half-written snapshot, and a
  failed run leaves the previous head serving.
- **Snapshots are immutable.** A given `snapshot_id` never changes content, so
  consumers may cache anything derived from it forever (keyed by id).
- **Heads move.** `code_heads.snapshot_id` changes when a newer commit is
  indexed. To pin to a version, remember the snapshot id (or `repo` + `sha`).
- **Retention.** The indexer keeps the newest N snapshots per repo (default 5),
  the current head, and any `pinned` snapshot. Anything else may disappear.

## 2. Graph JSON, schema version 1 (`code_snapshots.graph`)

A static dependency and call graph of one repository snapshot. Lossless:
a consumer can rebuild the full graph from it. Every `file` is
**repo-root-relative** (the indexer prefixes `source_root`), so it can be used
directly as `code_files.path`.

```json
{
  "schema_version": 1,
  "repo": "owner/name",
  "sha": "<full commit sha>",
  "extractor_version": "ast-1",
  "modules": ["app.payment_client", "app.order_service"],
  "symbols": {
    "<qualname>": {
      "kind": "module | class | function",
      "module": "app.payment_client",
      "file": "app/payment_client.py",
      "line": 22,
      "parent": "<qualname of the owning class, or null>"
    }
  },
  "imports": {
    "<importer module>": {
      "<imported module>": { "symbols": ["PaymentClient"], "wholesale": false, "line": 3 }
    }
  },
  "calls": [
    { "caller": "<qualname>", "target": "<qualname>", "file": "app/order_service.py", "line": 37 }
  ]
}
```

Field notes:

- `qualname` is the dotted path, e.g. `app.payment_client.PaymentClient.charge`.
- A **module-level call** has the module's own qualname as `caller`.
- `imports[importer][imported].wholesale` is true for `import x` (could use
  anything in it); `symbols` lists names pulled in by `from x import name`.
- Only imports of modules **inside** the analysed source root appear in
  `imports`; stdlib and third-party imports are absent.
- Output is deterministic: same files in, byte-identical JSON out.

### Known limits (documented, not bugs)

Best-effort static analysis of Python only: no inheritance/MRO resolution, no
dynamic dispatch, relative imports ignored, calls to code outside the analysed
source root dropped, and the graph is per repository (no cross-repo edges).

## 3. Qdrant `repo_docs` collection — phase 2

Reserved. A collection owned exclusively by the indexer, holding docs, specs
and ADRs from indexed repos: payload `{repo, sha, path, source, heading, text}`,
point ids stable `uuid5` over `repo:path:heading`, embeddings
`text-embedding-3-small` (1536 dimensions, cosine) so they match what consumers
query with. The indexer deletes a repo's points for older SHAs by filter.

## Versioning rules

- `schema_version` (integer, in the graph JSON and on `code_snapshots`) changes
  only for a **breaking** change to section 2. Additive changes (new optional
  fields) keep it.
- `extractor_version` (string) identifies the analyzer that produced a graph.
  Bumping it makes the indexer re-index every repo; it is part of the snapshot
  key, so old and new graphs can coexist briefly.
- **Consumers must check `schema_version`**, support an explicit set of
  versions, and refuse (with a clear message) any other rather than guess.
- A breaking change to tables in section 1 requires a coordinated release of
  the indexer and its consumers; announce it here first.

Current: `schema_version = 1`, `extractor_version = "ast-1"`.
