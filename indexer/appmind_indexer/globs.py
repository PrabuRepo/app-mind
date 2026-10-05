"""
appmind_indexer/globs.py — tiny glob matcher for repo-relative POSIX paths.

Python's fnmatch lets `*` cross `/` and has no `**`, which makes patterns like
`**/tests/**` behave unpredictably. Here `*` and `?` stay within one path
segment, `**/` matches zero or more directories, and `**` matches anything.
"""

from __future__ import annotations

import functools
import re


@functools.lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def matches_any(rel_path: str, patterns) -> bool:
    return any(_compile(p).match(rel_path) for p in patterns)
