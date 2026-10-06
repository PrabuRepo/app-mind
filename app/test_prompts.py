"""
app/test_prompts.py — the agent prompts name the application from the profile,
not from code.

    python -m app.test_prompts

No network or API key. For OrderFlow the rendered prompts are byte-identical to
the ones that were hardcoded before (verified against the previous source when
this landed); here a second, made-up application proves nothing else leaks in.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

from agents.critic import CRITIC_INSTRUCTIONS
from agents.evidence import EVIDENCE_INSTRUCTIONS
from agents.synthesis import BASELINE_INSTRUCTIONS, SYNTHESIS_INSTRUCTIONS
from app import prompts
from app_profile import parse_profile
from llm_as_judge.judge import JUDGE_INSTRUCTIONS

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = {
    "evidence": EVIDENCE_INSTRUCTIONS, "critic": CRITIC_INSTRUCTIONS, "synthesis": SYNTHESIS_INSTRUCTIONS,
    "baseline": BASELINE_INSTRUCTIONS, "judge": JUDGE_INSTRUCTIONS,
}

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def render_for(app: dict, template: str) -> str:
    prof = parse_profile({"schema_version": 1, "app": app, "sources": {"code": [{"repo": "acme/billing"}]}})
    prompts._names.cache_clear()
    with patch.object(prompts, "select_profile", return_value=prof):
        return prompts.render_prompt(template)


print("\n-- the templates hold placeholders, not an application --")
for name, template in TEMPLATES.items():
    check(f"{name}: names no application", "OrderFlow" not in template)
    check(f"{name}: has a placeholder", "{app_name}" in template or "{app_label}" in template)

print("\n-- a second application --")
billing = {"id": "billing", "name": "Billing", "description": "an invoicing service"}
for name, template in TEMPLATES.items():
    out = render_for(billing, template)
    check(f"{name}: names the profile's app", "Billing" in out)
    check(f"{name}: no OrderFlow and no leftover placeholder", "OrderFlow" not in out and "{app_" not in out)
check("baseline reads 'Billing, an invoicing service'", "about Billing, an invoicing service, " in
      render_for(billing, BASELINE_INSTRUCTIONS))
check("without a description the baseline names just the app",
      "about Billing, using" in render_for({"id": "billing", "name": "Billing"}, BASELINE_INSTRUCTIONS))
check("braces elsewhere in a prompt are untouched",
      render_for(billing, 'Reply as {"a": 1} for {app_name}') == 'Reply as {"a": 1} for Billing')

print("\n-- the real profile --")
prompts._names.cache_clear()
check("OrderFlow's label reproduces the old wording",
      prompts._names() == ("OrderFlow", "OrderFlow, an order-processing service"), str(prompts._names()))
prompts._names.cache_clear()

print("\n-- the call path and the UI --")
llm_source = (PROJECT_ROOT / "app" / "llm.py").read_text(encoding="utf-8")
check("structured_call renders the placeholders before calling the model",
      "instructions = render_prompt(instructions)" in llm_source)
ui_source = (PROJECT_ROOT / "ui" / "streamlit_app.py").read_text(encoding="utf-8")
check("the UI intro takes the app name from the profile and names no application",
      "select_profile().app.name" in ui_source and "OrderFlow" not in ui_source)

print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
raise SystemExit(1 if failures else 0)
