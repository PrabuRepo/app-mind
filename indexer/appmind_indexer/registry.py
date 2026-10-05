"""
appmind_indexer/registry.py — which repositories to index.

Phase 1 reads `targets.toml` (identifiers only; never repository content).
Uses the standard-library `tomllib`, so no extra dependency.
"""

from __future__ import annotations

import pathlib
import re
import tomllib
from dataclasses import dataclass

DEFAULT_TARGETS_PATH = pathlib.Path(__file__).resolve().parent.parent / "targets.toml"
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class Target:
    repo: str                       # "owner/name"
    ref: str = "main"
    source_root: str = "."
    exclude: tuple[str, ...] = ()
    docs: tuple[str, ...] = ()      # parsed now, indexed in phase 2
    language: str = "python"


class RegistryError(ValueError):
    pass


def _validate_source_root(source_root: str) -> str:
    parts = pathlib.PurePosixPath(source_root).parts
    if pathlib.PurePosixPath(source_root).is_absolute() or ".." in parts or "\\" in source_root:
        raise RegistryError(f"source_root must be a relative path inside the repo, got {source_root!r}")
    return source_root


def load_targets(path: pathlib.Path | str | None = None) -> list[Target]:
    path = pathlib.Path(path) if path else DEFAULT_TARGETS_PATH
    with path.open("rb") as f:
        data = tomllib.load(f)
    targets: list[Target] = []
    for entry in data.get("target", []):
        repo = entry.get("repo", "")
        if not _REPO_RE.match(repo):
            raise RegistryError(f"target repo must look like 'owner/name', got {repo!r}")
        targets.append(Target(
            repo=repo,
            ref=entry.get("ref", "main"),
            source_root=_validate_source_root(entry.get("source_root", ".")),
            exclude=tuple(entry.get("exclude", ())),
            docs=tuple(entry.get("docs", ())),
            language=entry.get("language", "python"),
        ))
    if not targets:
        raise RegistryError(f"no [[target]] entries in {path}")
    return targets
