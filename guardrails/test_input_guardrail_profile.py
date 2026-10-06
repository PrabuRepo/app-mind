"""
guardrails/test_input_guardrail_profile.py — the topic check takes its
reference text from the application profile.

    python -m guardrails.test_input_guardrail_profile

No API key needed: embeddings are replaced by a deterministic word-count
embedder, so these checks are about WIRING (which text is embedded, when the
check is skipped, what the block message names), not about score quality. The
real scores were measured live when the step landed; see the design doc.
"""

from __future__ import annotations

import re
from unittest.mock import patch

from app.schemas import GraphState
from app_profile import ProfileError, parse_profile
from guardrails import input_guardrail as ig

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


VOCAB = ["invoice", "ledger", "refund", "tax", "payment", "weather", "recipe", "football"]
embedded: list[tuple[str, str]] = []


def fake_embed(text: str, caller: str = "") -> list[float]:
    embedded.append((caller, text))
    words = re.findall(r"[a-z]+", text.lower())
    return [float(words.count(w)) + 0.01 for w in VOCAB]


def profile(scope: dict | None, name: str = "Billing"):
    doc = {"schema_version": 1, "app": {"id": "billing", "name": name},
           "sources": {"code": [{"repo": "acme/billing"}]}}
    if scope is not None:
        doc["scope"] = scope
    return parse_profile(doc)


def run(question: str, prof) -> dict:
    ig._topic.cache_clear()
    ig._topic_reference_vector.cache_clear()
    embedded.clear()
    with patch.object(ig, "select_profile", return_value=prof), patch.object(ig, "embed_query", fake_embed):
        return ig.input_guardrail(GraphState(question=question, pipeline_mode="critic_on"))


scoped = profile({"description": "Billing service: invoice, ledger, refund and tax payment handling for customers."})

print("\n-- with scope.description --")
out = run("How is a refund payment recorded in the ledger invoice?", scoped)
check("an on-topic question passes", not out.get("blocked"), str(out))
check("the reference text embedded is the profile's scope.description",
      ("input_guardrail_topic_reference", scoped.scope.description) in embedded, str(embedded))
check("the question itself is embedded once", sum(c == "input_guardrail_topic_check" for c, _ in embedded) == 1)
check("the embedding call is recorded in the trace", "llm:embedding" in out["trace"])

out = run("What is the weather and the football recipe tonight?", scoped)
check("an off-topic question is blocked", out.get("blocked") is True, str(out))
check("the block reason names the profile's app, not a hardcoded one",
      "Billing" in out["block_reason"] and "OrderFlow" not in out["block_reason"], out.get("block_reason", ""))
check("the block reason reports the threshold", str(ig.MIN_TOPIC_SCORE) in out["block_reason"])

print("\n-- without scope.description --")
for label, prof in (("no scope", profile(None)), ("scope: {}", profile({}))):
    out = run("What is the weather and the football recipe tonight?", prof)
    check(f"{label}: the topic check is skipped, so an off-topic question is not blocked", not out.get("blocked"), str(out))
    check(f"{label}: nothing is embedded (no API cost)", embedded == [], str(embedded))
    check(f"{label}: no llm:embedding in the trace", "llm:embedding" not in out["trace"])

print("\n-- PII still blocks first, with or without a scope --")
for prof in (scoped, profile(None)):
    out = run("Contact jane@example.com about the refund", prof)
    check("an email-shaped question is blocked before anything is embedded",
          out.get("blocked") is True and embedded == [], str(embedded))

print("\n-- failure modes --")
ig._topic.cache_clear()
ig._topic_reference_vector.cache_clear()
with patch.object(ig, "select_profile", side_effect=ProfileError("config/apps: no application profiles found")):
    try:
        ig.input_guardrail(GraphState(question="How is a refund recorded?", pipeline_mode="critic_on"))
        check("a broken profile is an error, not silently skipped", False)
    except ProfileError:
        check("a broken profile is an error, not silently skipped", True)

ig._topic.cache_clear()
ig._topic_reference_vector.cache_clear()


def failing_embed(text, caller=""):
    raise RuntimeError("network down")


with patch.object(ig, "select_profile", return_value=scoped), patch.object(ig, "embed_query", failing_embed):
    out = ig.input_guardrail(GraphState(question="How is a refund recorded?", pipeline_mode="critic_on"))
check("an embedding failure still fails open (question proceeds)", not out.get("blocked"), str(out))

ig._topic.cache_clear()
ig._topic_reference_vector.cache_clear()
print("\n-- the real profile --")
real = ig._topic()
check("the real OrderFlow profile supplies the app name and a description",
      real[0] == "OrderFlow" and real[1] is not None and "PaymentClient" in real[1])
ig._topic.cache_clear()

print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
raise SystemExit(1 if failures else 0)
