"""
app_profile/check.py — validate every profile under config/apps/ and the
OrderFlow example in the design folder.

    python -m app_profile.check

Exits non-zero on the first problem, so it can run in CI. Structural errors and
file-name/id problems are fatal. Secrets and paths are checked too, but an
environment variable that is not set is only a warning here (CI has no token);
use --strict to make it fatal where the secrets are expected, for example on
the machine that runs the indexer.
"""

from __future__ import annotations

import sys

from app_profile.loader import ProfileError, load_profile
from app_profile.registry import PROFILES_DIR, PROJECT_ROOT, load_all
from app_profile.semantic import check_profile

EXAMPLE = PROJECT_ROOT / "features" / "appmind-config" / "orderflow.example.yaml"


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    failed = False
    try:
        profiles = load_all(PROFILES_DIR)
        load_profile(EXAMPLE)
    except ProfileError as exc:
        print(f"FAIL  {exc}")
        return 1

    for name, profile in profiles.items():
        problems = check_profile(profile, PROJECT_ROOT)
        fatal = [p for p in problems if "environment variable" not in p or strict]
        warnings = [p for p in problems if p not in fatal]
        for p in warnings:
            print(f"WARN  {name}: {p}")
        for p in fatal:
            print(f"FAIL  {name}: {p}")
        if fatal:
            failed = True
        else:
            print(f"OK    {name} (app.id {profile.app.id})")
    print(f"OK    {EXAMPLE.name} (design example)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
