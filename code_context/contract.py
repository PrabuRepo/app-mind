"""
code_context/contract.py — what AppMind agrees to about the indexer's data.

Mirrors indexer/CONTRACT.md. A snapshot whose graph `schema_version` is not in
SUPPORTED_SCHEMA_VERSIONS is refused with a clear error, never misread.
"""

from __future__ import annotations

SUPPORTED_SCHEMA_VERSIONS = frozenset({1})


class CodeContextError(RuntimeError):
    """Base for every failure reading the code knowledge store. Callers that
    must never crash (the retrieval path) catch this one type."""


class NoSnapshot(CodeContextError):
    """Nothing indexed yet for the requested repo (or the tables don't exist)."""


class IndexUnavailable(CodeContextError):
    """The store could not be reached or queried (database down, bad credentials...)."""


class UnsupportedSchemaVersion(CodeContextError):
    """A snapshot uses a graph schema version this AppMind does not support."""


class InvalidSnapshot(CodeContextError):
    """A snapshot's graph JSON is missing required fields or is malformed."""
