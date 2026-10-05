"""Tiny shared test helpers. Tests are plain runnable modules (no pytest
dependency): `python -m tests.test_extract` from the indexer/ folder."""

from __future__ import annotations

import pathlib

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "orderflow"


class Checker:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def section(self, title: str) -> None:
        print(f"\n== {title} ==")

    def __call__(self, name: str, ok: bool, detail: str = "") -> None:
        print(("  PASS  " if ok else "  FAIL  ") + name + (f"  [{detail}]" if detail and not ok else ""))
        if not ok:
            self.failures.append(name)

    def finish(self) -> int:
        if self.failures:
            print(f"\n{len(self.failures)} CHECK(S) FAILED: " + "; ".join(self.failures))
            return 1
        print("\nALL CHECKS PASSED")
        return 0
