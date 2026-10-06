"""
code_context/test_boundaries.py — guards the repository boundary around the
indexer (features/code-index-design.md, section 5.6).

    python -m code_context.test_boundaries

The indexer (indexer/) will move to its own repository. That stays a simple
relocation only if the two sides never import each other, so this test fails
the moment someone creates a cross-import:

  1. no AppMind code imports the indexer package (appmind_indexer)
  2. no indexer code imports an AppMind package
  3. the indexer imports only the standard library, itself, and the
     dependencies listed in indexer/requirements.txt (so its image is complete)

Only the standard library is needed to run it.
"""

from __future__ import annotations

import ast
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEXER_DIR = PROJECT_ROOT / "indexer"

# Every top-level package of AppMind (the repo root's own modules count too).
APPMIND_PACKAGES = {
    "app", "agents", "rag", "memory", "mcp_servers", "mcp_clients", "guardrails",
    "ingest", "evals", "llm_as_judge", "ui", "code_context", "app_profile",
}
# Sample source code the indexer's extractor is tested on; it is DATA, not
# indexer code, and legitimately imports things like `app.models`.
INDEXER_FIXTURES = INDEXER_DIR / "tests" / "fixtures"
# Import names for the packages in indexer/requirements.txt.
INDEXER_ALLOWED_THIRD_PARTY = {"psycopg", "httpx", "dotenv"}
INDEXER_OWN = {"appmind_indexer", "tests"}

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def imports_of(path: pathlib.Path) -> set[str]:
    """Top-level names imported by a Python file (absolute imports only)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def appmind_files() -> list[pathlib.Path]:
    files = [p for p in PROJECT_ROOT.glob("*.py")]
    for pkg in APPMIND_PACKAGES:
        files += [p for p in (PROJECT_ROOT / pkg).rglob("*.py") if "__pycache__" not in p.parts]
    return files


def indexer_files() -> list[pathlib.Path]:
    return [p for p in INDEXER_DIR.rglob("*.py")
            if "__pycache__" not in p.parts and INDEXER_FIXTURES not in p.parents]


def main() -> int:
    print("== AppMind never imports the indexer ==")
    offenders = [str(p.relative_to(PROJECT_ROOT)) for p in appmind_files() if "appmind_indexer" in imports_of(p)]
    check("no AppMind file imports appmind_indexer", not offenders, str(offenders))

    print("\n== the indexer never imports AppMind ==")
    files = indexer_files()
    check("found the indexer's own source files", len(files) >= 8, str(len(files)))
    offenders = [f"{p.relative_to(PROJECT_ROOT)}: {sorted(imports_of(p) & APPMIND_PACKAGES)}"
                 for p in files if imports_of(p) & APPMIND_PACKAGES]
    check("no indexer file imports an AppMind package", not offenders, str(offenders))

    print("\n== the indexer's imports are self-contained ==")
    stdlib = set(sys.stdlib_module_names)
    allowed = stdlib | INDEXER_OWN | INDEXER_ALLOWED_THIRD_PARTY | {"__future__"}
    offenders = [f"{p.relative_to(PROJECT_ROOT)}: {sorted(imports_of(p) - allowed)}"
                 for p in files if imports_of(p) - allowed]
    check("every import is stdlib, the indexer itself, or in its requirements.txt", not offenders, str(offenders))
    requirements = (INDEXER_DIR / "requirements.txt").read_text(encoding="utf-8").lower()
    check("its requirements.txt lists the third-party packages it imports",
          all(name in requirements for name in ("psycopg", "httpx", "python-dotenv")))
    check("its requirements.txt does not drag in AppMind-only packages",
          not any(name in requirements for name in ("langgraph", "streamlit", "openai", "qdrant", "mcp")))
    for required in ("README.md", "CONTRACT.md", "Dockerfile", "requirements.txt", "targets.example.toml"):
        check(f"indexer/{required} exists (a repo needs it standalone)", (INDEXER_DIR / required).is_file())

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
