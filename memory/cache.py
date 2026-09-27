"""
memory/cache.py — Redis-backed lookup cache so a repeated question can be
answered from a previous investigation instead of re-running the whole
pipeline (the "basic memory/context" line item — see memory/memory_write.py
and app/investigate.py for where this is written/read).

Keyed on (normalized question, pipeline_mode). pipeline_mode MUST be part of
the key: this project's entire comparative eval rests on baseline/critic_off/
critic_on producing genuinely different answers for the same question, so a
critic_on entry must never be served back for a baseline lookup, or vice
versa. evals/run_eval.py deliberately never calls into this module at all —
see app/investigate.py's docstring for why.

Like memory/db.py, every function here is best-effort: a Redis outage must
look exactly like an ordinary cache miss to the caller, never a crash.
"""

from __future__ import annotations

import functools
import os
import re

import redis
from dotenv import load_dotenv

from app.schemas import DecisionBrief, PipelineMode

CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h: the knowledge-domains corpus is static for the capstone window


@functools.lru_cache(maxsize=1)
def _get_redis() -> redis.Redis:
    load_dotenv()
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(url, socket_connect_timeout=3, socket_timeout=3, decode_responses=True)


def _normalize(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


def cache_key(question: str, pipeline_mode: PipelineMode) -> str:
    return f"appmind:investigation:{pipeline_mode.value}:{_normalize(question)}"


def get_cached(question: str, pipeline_mode: PipelineMode) -> DecisionBrief | None:
    try:
        raw = _get_redis().get(cache_key(question, pipeline_mode))
    except Exception as exc:  # connection refused, timeout...
        print(f"[cache] GET failed, treating as a miss: {type(exc).__name__}: {str(exc)[:200]}")
        return None
    if raw is None:
        return None
    try:
        return DecisionBrief.model_validate_json(raw)
    except Exception as exc:  # a stale/incompatible cached shape
        print(f"[cache] cached value failed to parse, treating as a miss: {exc}")
        return None


def set_cached(question: str, pipeline_mode: PipelineMode, brief: DecisionBrief) -> None:
    try:
        _get_redis().setex(cache_key(question, pipeline_mode), CACHE_TTL_SECONDS, brief.model_dump_json())
    except Exception as exc:
        print(f"[cache] SET failed, continuing without caching: {type(exc).__name__}: {str(exc)[:200]}")
