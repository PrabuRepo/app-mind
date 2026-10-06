"""
app_profile/semantic.py — checks the JSON schema cannot express: does what the
profile points at actually exist? Each function returns a list of problems
(empty means fine) so a caller can report them all at once.

Repository reachability is deliberately not here: it needs a token and the
network, so it is opt-in and added with the indexer hand-off (plan step 5).
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterable, Mapping

from app_profile.loader import AppProfile


def check_profile(
    profile: AppProfile,
    base_dir: str | pathlib.Path = ".",
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Secrets are set, and every local docs/incidents path exists.

    `base_dir` is what relative `path` entries resolve against (the repo root).
    """
    env = os.environ if env is None else env
    base = pathlib.Path(base_dir)
    problems: list[str] = []

    for source in profile.sources.code:
        if not env.get(source.secret):
            problems.append(f"sources.code {source.repo}: environment variable {source.secret} is not set")

    for group in ("docs", "incidents"):
        for entry in getattr(profile.sources, group):
            if entry.path is not None:
                if not (base / entry.path).exists():
                    problems.append(f"sources.{group}: path '{entry.path}' does not exist (looked in {base.resolve()})")
            elif not env.get(entry.secret):
                problems.append(f"sources.{group} {entry.repo}: environment variable {entry.secret} is not set")

    return problems


def check_unique_ids(profiles: Iterable[tuple[str, AppProfile]]) -> list[str]:
    """`app.id` must be unique across profiles, and match the file name."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for filename, profile in profiles:
        app_id = profile.app.id
        stem = pathlib.Path(filename).stem
        if stem != app_id:
            problems.append(f"{filename}: file name must match app.id '{app_id}'")
        if app_id in seen:
            problems.append(f"{filename}: app.id '{app_id}' is already used by {seen[app_id]}")
        else:
            seen[app_id] = filename
    return problems
