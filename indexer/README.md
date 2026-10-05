# appmind-indexer

A self-contained batch job that turns repositories into a **knowledge store**:
for each configured repo it resolves a commit SHA, downloads that exact commit,
builds a static dependency/call graph, and writes the graph and the source
files to Postgres, tagged with `repo` and `sha`. Applications (AppMind) then
answer questions from the store without ever touching the repositories.

It imports nothing from AppMind and shares no code with it. The only
interface is the data described in [`CONTRACT.md`](CONTRACT.md). That is what
lets this folder move to its own repository unchanged.

## How it works

```
targets.toml ──> resolve ref to a commit SHA ──> already indexed? ──yes──> confirm head, done
                                                        │ no
                                                        v
        download tarball to a temp dir ──> extract graph + collect source files
                                                        │
                                                        v
        ONE transaction: snapshot + files + head pointer ──> prune old snapshots ──> delete temp dir
```

- **Atomic per repo:** a failed run leaves the previous snapshot serving.
- **Idempotent:** an unchanged commit is skipped, so running it on a schedule is cheap.
- **Isolated per target:** one failing repo never stops the others; the process
  exits non-zero if any failed.
- **Nothing is kept:** repositories are extracted into a temporary directory
  that is deleted afterwards; only derived data is stored.
- **Audited:** every run is recorded in `index_runs`.

## Layout

```
indexer/
├── README.md, CONTRACT.md      this file, and the data contract
├── Dockerfile, requirements.txt
├── targets.toml                the registry: which repos to index
├── appmind_indexer/
│   ├── config.py               env-driven settings
│   ├── registry.py             loads and validates targets.toml
│   ├── fetch.py                resolve a SHA, download + safely extract a tarball
│   ├── extract/
│   │   ├── files.py            collect source files
│   │   └── python_ast.py       build the graph JSON (schema v1)
│   ├── store.py                the schema and all writes
│   └── run.py                  the command line
└── tests/                      standalone tests + a sample source tree fixture
```

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `GITHUB_TOKEN` | Fine-grained token with **read-only Contents** access to the target repos | required |
| `POSTGRES_HOST` / `PORT` / `DB` / `USER` / `PASSWORD` | Where to write | `localhost` / `5432` / `appmind` / `appmind` / `appmind` |
| `APPMIND_INDEXER_KEEP` | Snapshots kept per repo (the head and pinned ones are always kept) | `5` |

A `.env` file is loaded if one is found. In Docker, pass variables through the
environment; `.env` is not copied into the image.

### Adding a repository

Add a block to `targets.toml`:

```toml
[[target]]
repo        = "owner/name"
ref         = "main"
source_root = "."                  # or "src" if the code lives in a subdirectory
exclude     = ["**/tests/**"]      # extra globs; .venv, node_modules, etc. are already skipped
```

`source_root` matters: module names are derived from paths relative to it, and
the code is expected to import its own modules by absolute name from there.

## Running it

From this folder (needs `pip install -r requirements.txt`):

```bash
python -m appmind_indexer.run                    # every target
python -m appmind_indexer.run --repo owner/name  # one target
python -m appmind_indexer.run --force            # re-index even if this commit is already indexed
python -m appmind_indexer.run --pin              # exempt the new snapshot from pruning
```

In Docker (from the repository that contains this folder and a compose file):

```bash
docker compose run --rm indexer
```

The image is built from this folder alone, so it cannot contain or import
anything outside it.

## Tests

Plain runnable modules, no test framework. They need the Postgres container
(real database, no mocks); the live checks also use `GITHUB_TOKEN` if present.

```bash
python -m tests.run_all          # everything
python -m tests.test_extract     # or one module
```

## Limits

Python only; static analysis is best-effort (see `CONTRACT.md`). Docs/specs
indexing into a vector collection is planned (phase 2): a `docs` field in
`targets.toml` is accepted but not yet used.
