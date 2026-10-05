"""Run every indexer test module:  python -m tests.run_all   (from indexer/)"""

from __future__ import annotations

import importlib

MODULES = ["test_registry", "test_extract", "test_fetch", "test_store", "test_run"]


def main() -> int:
    failed = []
    for name in MODULES:
        print(f"\n########## {name} ##########")
        if importlib.import_module(f"tests.{name}").main() != 0:
            failed.append(name)
    print("\n" + ("ALL TEST MODULES PASSED" if not failed else f"FAILED MODULES: {failed}"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
