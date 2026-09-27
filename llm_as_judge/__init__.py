"""
llm_as_judge — NOT YET IMPLEMENTED.

Reserved for the "should-have" eval metric in CLAUDE.md's priority-6 harness:
an LLM-as-judge that scores citation accuracy (does the cited source really
say what the brief claims?) for the results evals/ produces.

This is a narrower, project-specific use than the standalone LLM-as-judge
lab exercise impl-plan.md defers to after submission (a judge harness tested
against known-good/known-bad pairs, studied as a technique on its own). This
package is only the in-project judge; the standalone exercise is out of scope
here by design.
"""

from __future__ import annotations
