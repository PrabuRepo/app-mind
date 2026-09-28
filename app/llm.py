"""
app/llm.py — one small wrapper for every LLM call in AppMind.

Keeping all calls behind a single function means there is exactly one place
that (a) picks the model, (b) counts tokens for the cost metric, and (c)
turns a failure into a value instead of an exception — the same "never crash,
record the problem" rule app/retrieval.py follows.

STRUCTURED OUTPUT:
We don't ask the model to "reply in JSON" and hope. We hand the API a
Pydantic class and it constrains the reply to that exact shape, returning an
already-parsed object. A malformed reply becomes impossible rather than
something to defend against with string parsing.

MODEL CHOICE:
Defaults to gpt-5.4-mini. Set APPMIND_LLM_MODEL=gpt-5.4-nano to switch
without touching code — this is how the eval harness will compare cost and
latency between the two before a final choice is made.
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel

from ingest.run_ingestion import load_env_and_clients

DEFAULT_MODEL = "gpt-5.4-mini"
LLM_TIMEOUT_S = 60.0   # the SDK default is 10 minutes; a hung call must not stall an investigation

T = TypeVar("T", bound=BaseModel)


@functools.lru_cache(maxsize=1)
def _openai():
    return load_env_and_clients()[0]


def model_name() -> str:
    # Read at call time (not import time) so a test or eval run can switch models.
    return os.environ.get("APPMIND_LLM_MODEL", DEFAULT_MODEL)


@dataclass
class LLMResult(Generic[T]):
    parsed: T | None = None
    tokens: int = 0            # input + output tokens for this call
    error: str | None = None


def structured_call(instructions: str, user_input: str, schema: type[T],
                    max_output_tokens: int = 3000, caller: str = "llm") -> LLMResult[T]:
    """One LLM call whose reply is parsed into `schema`. Never raises.

    `caller` is just a label for the `[llm]` log line below (e.g. "evidence",
    "critic") — it has no effect on the call itself. Pass it so the log shows
    WHICH agent triggered a given API call, not just that one happened.
    """
    model = model_name()
    print(f"[llm] {caller}: calling {model} ({schema.__name__})")
    try:
        response = _openai().responses.parse(
            model=model,
            instructions=instructions,
            input=user_input,
            text_format=schema,
            max_output_tokens=max_output_tokens,
            timeout=LLM_TIMEOUT_S,
        )
    except Exception as exc:  # network, auth, rate limit, timeout, schema rejection...
        error = f"LLM call failed ({model}): {type(exc).__name__}: {str(exc)[:200]}"
        print(f"[llm] {caller}: FAILED — {error}")
        return LLMResult(error=error)
    tokens = response.usage.total_tokens if response.usage else 0
    if response.output_parsed is None:
        error = f"LLM ({model}) returned no parseable output (refusal or truncation)"
        print(f"[llm] {caller}: {model} responded with no parseable output, {tokens} tokens")
        return LLMResult(tokens=tokens, error=error)
    print(f"[llm] {caller}: {model} responded ok, {tokens} tokens")
    return LLMResult(parsed=response.output_parsed, tokens=tokens)
