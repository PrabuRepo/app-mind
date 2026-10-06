"""
app/component_hints.py — which code component a question is about when the
question never names it ("charged twice" means PaymentClient).

The words come from the application profile's `scope.aliases`, not from code,
so this module knows nothing about any particular application. It is only a
fallback: mcp_clients/ast_client.py matches component names written in the
question against the code graph first, and uses this result only when that
finds nothing.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping, Sequence

from app_profile.registry import select_profile


def component_from_aliases(question: str, aliases: Mapping[str, Sequence[str]]) -> str | None:
    """The first component (in profile order) with an alias that appears in the
    question, ignoring case. A word matches as part of a word, so "invent"
    matches "inventory". None when nothing matches."""
    text = question.lower()
    for component, words in aliases.items():
        if any(word.lower() in text for word in words):
            return component
    return None


@functools.lru_cache(maxsize=1)
def _profile_aliases() -> dict[str, tuple[str, ...]]:
    """Read once per process. A broken profile raises, as in the guardrail."""
    return dict(select_profile().scope.aliases)


def component_hint(question: str) -> str | None:
    """component_from_aliases() with the active application profile's aliases."""
    return component_from_aliases(question, _profile_aliases())
