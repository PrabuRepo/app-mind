"""
appmind_indexer/run.py — the command-line entry point.

    python -m appmind_indexer.run                       # index every target in targets.toml
    python -m appmind_indexer.run --repo owner/name     # just one target
    python -m appmind_indexer.run --force               # re-index even if this SHA is already indexed
    python -m appmind_indexer.run --pin                 # exempt the new snapshot from pruning (eval pins)

Each target is indexed independently: one failing repo never stops the rest.
The process exits non-zero if any target failed — a batch job may fail loudly.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile
import time

from appmind_indexer import config, fetch, store
from appmind_indexer.extract.files import collect_python_files, normalize_prefix
from appmind_indexer.extract.python_ast import EXTRACTOR_VERSION, SCHEMA_VERSION, build_graph_json
from appmind_indexer.registry import Target, load_targets


def index_target(conn, target: Target, *, token: str, force: bool, pin: bool, trigger: str) -> str:
    """Index one target. Returns 'succeeded', 'skipped' or 'failed'."""
    started = time.perf_counter()
    run_id = store.start_run(conn, target.repo, trigger)
    sha: str | None = None
    try:
        sha = fetch.resolve_sha(target.repo, target.ref, token)
        print(f"[index] {target.repo}@{target.ref} -> {sha[:7]}")

        existing = store.find_snapshot(conn, target.repo, sha, EXTRACTOR_VERSION)
        if existing and not force:
            store.set_head(conn, target.repo, existing)
            conn.commit()
            store.finish_run(conn, run_id, "skipped", sha)
            print(f"[index] {target.repo}: {sha[:7]} already indexed, head confirmed (skipped)")
            return "skipped"

        if target.docs:
            print(f"[index] {target.repo}: 'docs' is configured but docs indexing arrives in phase 2; ignoring")

        with tempfile.TemporaryDirectory(prefix="appmind-indexer-") as tmp:
            repo_root = fetch.download_tarball(target.repo, sha, token, pathlib.Path(tmp))
            source_root = (repo_root / target.source_root).resolve()
            if repo_root.resolve() not in (source_root, *source_root.parents) or not source_root.is_dir():
                raise RuntimeError(f"source_root {target.source_root!r} is not a directory inside the repo")
            files, skipped_files = collect_python_files(
                source_root, source_prefix=normalize_prefix(target.source_root), exclude=target.exclude,
            )
            print(f"[index] {target.repo}: fetched and read {len(files)} source file(s)")
            extraction = build_graph_json(files, repo=target.repo, sha=sha)

        stats = {**extraction.stats, "skipped_files": [*skipped_files, *extraction.skipped]}
        snapshot_id = store.write_snapshot(
            conn, repo=target.repo, ref=target.ref, sha=sha, source_root=target.source_root,
            extractor_version=EXTRACTOR_VERSION, schema_version=SCHEMA_VERSION,
            graph=extraction.graph, stats=stats, files=files, pinned=pin,
            replace_existing=bool(existing),
        )
        pruned = store.prune(conn, target.repo, config.snapshots_to_keep())
        store.finish_run(conn, run_id, "succeeded", sha)
        print(f"[index] {target.repo}@{sha[:7]}: snapshot {snapshot_id[:8]} written "
              f"({extraction.stats['symbols']} symbols, {extraction.stats['call_edges']} call edges, "
              f"{len(files)} files, {len(stats['skipped_files'])} skipped, {pruned} old snapshot(s) pruned) "
              f"in {time.perf_counter() - started:.1f}s")
        return "succeeded"
    except Exception as exc:
        conn.rollback()
        message = f"{type(exc).__name__}: {str(exc)[:500]}"
        store.finish_run(conn, run_id, "failed", sha, error=message)
        print(f"[index] {target.repo}: FAILED — {message}", file=sys.stderr)
        return "failed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index repositories into the AppMind knowledge store")
    parser.add_argument("--repo", help="only this target (owner/name)")
    parser.add_argument("--targets", help="path to a targets.toml (default: the one next to this package)")
    parser.add_argument("--force", action="store_true", help="re-index even if this SHA is already indexed")
    parser.add_argument("--pin", action="store_true", help="exempt the new snapshot from pruning")
    parser.add_argument("--trigger", default="cli", choices=["cli", "compose", "webhook", "schedule"])
    args = parser.parse_args(argv)

    targets = load_targets(args.targets)
    if args.repo:
        targets = [t for t in targets if t.repo == args.repo]
        if not targets:
            print(f"[index] no target {args.repo!r} in the registry", file=sys.stderr)
            return 2

    token = config.github_token()
    results: dict[str, str] = {}
    with store.connect() as conn:
        store.ensure_schema(conn)
        for target in targets:
            results[target.repo] = index_target(
                conn, target, token=token, force=args.force, pin=args.pin, trigger=args.trigger,
            )

    print("[index] summary: " + ", ".join(f"{repo}={status}" for repo, status in results.items()))
    return 1 if "failed" in results.values() else 0


if __name__ == "__main__":
    raise SystemExit(main())
