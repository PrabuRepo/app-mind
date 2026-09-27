"""
memory/test_cache.py — tests memory/cache.py against the REAL local Redis
container (per CLAUDE.md: real connections, not mocks). Round-trips a brief,
confirms pipeline_mode isolation (a critic_on write must not satisfy a
baseline lookup of the same question — see memory/cache.py's docstring for
why that matters), and confirms a broken connection degrades to a cache miss
instead of raising.

    python -m memory.test_cache
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import redis

from app.schemas import DecisionBrief, PipelineMode
from memory import cache

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def test_round_trip_and_normalization() -> None:
    print("== set_cached / get_cached round-trip ==")
    question = f"  Test Question {uuid.uuid4()}  "
    brief = DecisionBrief(answer="a", citations=[], confidence_rationale="r")

    check("miss before write", cache.get_cached(question, PipelineMode.CRITIC_ON) is None)
    cache.set_cached(question, PipelineMode.CRITIC_ON, brief)

    hit = cache.get_cached(question, PipelineMode.CRITIC_ON)
    check("hit after write", hit is not None)
    check("content matches", hit is not None and hit.answer == "a")

    differently_cased = question.strip().upper()
    check(
        "normalization: differently-cased/whitespaced question still hits",
        cache.get_cached(differently_cased, PipelineMode.CRITIC_ON) is not None,
    )


def test_pipeline_mode_isolation() -> None:
    print("== pipeline_mode isolation ==")
    question = f"mode isolation test {uuid.uuid4()}"
    brief = DecisionBrief(answer="critic_on answer", citations=[], confidence_rationale="r")
    cache.set_cached(question, PipelineMode.CRITIC_ON, brief)
    check(
        "a baseline lookup of the same question does not hit the critic_on entry",
        cache.get_cached(question, PipelineMode.BASELINE) is None,
    )


def test_degrades_on_bad_connection() -> None:
    print("== get_cached/set_cached degrade gracefully when Redis is unreachable ==")
    bad_client = redis.Redis(host="localhost", port=1, socket_connect_timeout=1, socket_timeout=1)
    with patch.object(cache, "_get_redis", return_value=bad_client):
        result = cache.get_cached("anything", PipelineMode.CRITIC_ON)
        check("get_cached returns None instead of raising", result is None)
        try:
            cache.set_cached("anything", PipelineMode.CRITIC_ON, DecisionBrief(answer="a", citations=[], confidence_rationale="r"))
            check("set_cached does not raise", True)
        except Exception as exc:
            check("set_cached does not raise", False, str(exc))


if __name__ == "__main__":
    test_round_trip_and_normalization()
    test_pipeline_mode_isolation()
    test_degrades_on_bad_connection()
    print(f"\n{len(failures)} failure(s)" if failures else "\nAll checks passed.")
    raise SystemExit(1 if failures else 0)
