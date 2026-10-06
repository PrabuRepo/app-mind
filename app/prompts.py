"""
app/prompts.py — fills the application's name into prompt text.

The agent prompts say "a software application ({app_name})" instead of naming
one application, so the same prompts serve whichever application the profile
describes. Two placeholders, read from the application profile:

    {app_name}   app.name                         "OrderFlow"
    {app_label}  app.name, then app.description   "OrderFlow, an order-processing service"
                 (just the name when there is no description)

Plain string replacement, not str.format, so braces elsewhere in a prompt
(JSON examples, for instance) are left alone.
"""

from __future__ import annotations

import functools

from app_profile.registry import select_profile


@functools.lru_cache(maxsize=1)
def _names() -> tuple[str, str]:
    """(name, label) from the active profile, read once per process. A broken
    profile raises, as everywhere else the profile is read."""
    app = select_profile().app
    return app.name, f"{app.name}, {app.description}" if app.description else app.name


def render_prompt(template: str) -> str:
    name, label = _names()
    return template.replace("{app_name}", name).replace("{app_label}", label)
