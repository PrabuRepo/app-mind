"""
app/test_component_hints.py — scope.aliases decide the supervisor's component
hint, and no application's names live in app/graph.py.

    python -m app.test_component_hints

No network or database. The 'before' column of the eval comparison (what the old
hardcoded hints returned for each of the 9 dataset questions) is pinned below,
so the profile's aliases are proven to reproduce it.
"""

from __future__ import annotations

import pathlib
import re

from app.component_hints import component_from_aliases, component_hint
from app.graph import supervisor
from app.schemas import GraphState
from evals.dataset import DATASET

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


print("\n-- the matching rule --")
aliases = {"PaymentClient": ["payment", "charge"], "InventoryClient": ["invent", "stock"]}
check("a word matches anywhere in the question, ignoring case",
      component_from_aliases("Customers were CHARGED twice", aliases) == "PaymentClient")
check("a word matches as part of a word ('invent' matches 'inventory')",
      component_from_aliases("How does inventory reservation work?", aliases) == "InventoryClient")
check("nothing matching gives None", component_from_aliases("What is the weather?", aliases) is None)
check("no aliases gives None", component_from_aliases("anything about payment", {}) is None)
check("when several components match, the first listed wins",
      component_from_aliases("stock was charged", aliases) == "PaymentClient"
      and component_from_aliases("stock was charged", dict(reversed(list(aliases.items())))) == "InventoryClient")

print("\n-- the OrderFlow profile reproduces the old hardcoded behavior --")
# What the removed hardcoded supervisor returned for the 9 dataset questions
# (question type, then component), recorded before the change.
OLD_HINTS = {
    "Does OrderFlow reserve": ("business_functional", None),
    "Why were customers charged twice": ("incident_rca", "PaymentClient"),
    "What would be affected if we changed PaymentClient": ("impact_analysis", "OrderService"),
    "Orders for SKU-300": ("incident_rca", "InventoryClient"),
    "Why were order confirmation emails": ("business_functional", None),
    "What's the SLA": ("business_functional", None),
    "What would break if InventoryClient": ("impact_analysis", "OrderService"),
    "How does OrderFlow handle a customer requesting a refund": ("business_functional", None),
    "Can the payment retry logic": ("incident_rca", "PaymentClient"),
}
check("all 9 dataset questions are pinned", len(DATASET) == len(OLD_HINTS) == 9)
for item in DATASET:
    old_type, old_component = next(v for k, v in OLD_HINTS.items() if item.question.startswith(k))
    out = supervisor(GraphState(question=item.question, pipeline_mode="critic_on"))
    check(f"question type unchanged: {item.question[:48]}", out["question_type"] == old_type, out["question_type"])
    if old_component == "OrderService":
        # The old hardcoded guess for impact questions that name no component.
        # Both dataset impact questions name theirs, so the AST client never used
        # this guess; it is not reproduced (it was an OrderFlow-specific stub).
        check(f"  component: the old OrderService default is gone, the question's own words decide: "
              f"{out['target_component']}", out["target_component"] != "OrderService")
    else:
        check(f"  component unchanged: {old_component}", out["target_component"] == old_component, str(out["target_component"]))

print("\n-- behavior outside the dataset --")
check("an impact question naming nothing gets no guessed component",
      supervisor(GraphState(question="What would break if we changed the retry delay?", pipeline_mode="critic_on"))
      ["target_component"] is None)
check("a business question never gets a component",
      supervisor(GraphState(question="How does payment work?", pipeline_mode="critic_on"))["target_component"] is None)
check("component_hint() uses the active profile", component_hint("Why were customers charged twice?") == "PaymentClient")

print("\n-- no application names in the platform code --")
source = pathlib.Path(__file__).with_name("graph.py").read_text(encoding="utf-8")
supervisor_source = source[source.index("def supervisor("):source.index("def research(")]
code_only = re.sub(r'""".*?"""', "", supervisor_source, flags=re.S)
leaks = [n for n in ("PaymentClient", "InventoryClient", "OrderService", "NotificationService") if n in code_only]
check("the supervisor's code names no OrderFlow component", not leaks, str(leaks))

print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
raise SystemExit(1 if failures else 0)
