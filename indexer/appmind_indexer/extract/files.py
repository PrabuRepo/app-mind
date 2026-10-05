"""
appmind_indexer/extract/files.py — collect the source files of one repository
snapshot from a directory on disk.

Reads each file once into memory as exact UTF-8 text. Exactness matters: the
text is stored verbatim and AppMind's Evidence agent later checks quotes
against it, so nothing here normalizes, strips, or re-encodes content.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from appmind_indexer.globs import matches_any

MAX_FILE_BYTES = 200_000

# Directories that are never first-party source, in any repository.
DEFAULT_EXCLUDES = (
    "**/.git/**",
    "**/__pycache__/**",
    "**/.venv/**",
    "**/venv/**",
    "**/node_modules/**",
    "**/site-packages/**",
)


@dataclass(frozen=True)
class SourceFile:
    path: str          # repo-root-relative, POSIX: what citations and the contract use
    rel: str           # source-root-relative, POSIX: what module names are derived from
    language: str
    size_bytes: int
    content: str


def normalize_prefix(source_root: str) -> str:
    """'.' (or '') -> '' ; 'src/' -> 'src'."""
    return "" if source_root in ("", ".") else source_root.strip("/")


def collect_python_files(
    root: pathlib.Path,
    *,
    source_prefix: str = "",
    exclude=(),
) -> tuple[list[SourceFile], list[dict]]:
    """Every .py file under `root` (the source root), minus exclusions.

    Returns (files, skipped). A file that is oversized, not UTF-8, or contains
    a NUL byte (which Postgres TEXT cannot hold) is skipped and reported, not
    fatal — one odd file must not block indexing a whole repository.
    """
    patterns = (*DEFAULT_EXCLUDES, *exclude)
    prefix = normalize_prefix(source_prefix)
    files: list[SourceFile] = []
    skipped: list[dict] = []

    for abs_path in sorted(root.rglob("*.py")):
        rel = abs_path.relative_to(root).as_posix()
        if matches_any(rel, patterns):
            continue
        path = f"{prefix}/{rel}" if prefix else rel
        if abs_path.is_symlink() or not abs_path.is_file():
            continue
        size = abs_path.stat().st_size
        if size > MAX_FILE_BYTES:
            skipped.append({"path": path, "reason": f"larger than {MAX_FILE_BYTES} bytes"})
            continue
        try:
            content = abs_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append({"path": path, "reason": "not valid UTF-8"})
            continue
        if "\x00" in content:
            skipped.append({"path": path, "reason": "contains a NUL byte"})
            continue
        files.append(SourceFile(path=path, rel=rel, language="python", size_bytes=size, content=content))
    return files, skipped
