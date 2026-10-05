"""
appmind_indexer/config.py — environment-driven settings.

Connection details come from environment variables with local-development
defaults; a `.env` file is loaded if one is found. This project keeps its own
copy of these conventions on purpose: it must not import anything from
AppMind (see CONTRACT.md).
"""

from __future__ import annotations

import functools
import os

from dotenv import load_dotenv


@functools.lru_cache(maxsize=1)
def _load_env() -> None:
    load_dotenv()


def github_token() -> str:
    _load_env()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set (a fine-grained, read-only Contents token)")
    return token


def postgres_dsn() -> str:
    _load_env()
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB", "appmind")
    user = os.environ.get("POSTGRES_USER", "appmind")
    password = os.environ.get("POSTGRES_PASSWORD", "appmind")
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


def snapshots_to_keep() -> int:
    _load_env()
    return int(os.environ.get("APPMIND_INDEXER_KEEP", "5"))
