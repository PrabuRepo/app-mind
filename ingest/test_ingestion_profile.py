"""
ingest/test_ingestion_profile.py — ingestion takes its folders from the
application profile.

    python -m ingest.test_ingestion_profile

No network, Qdrant or API key needed: it only chunks files. (The one-off proof
that the chunks equal what is stored in Qdrant was run when the step landed.)
"""

from __future__ import annotations

import pathlib
import tempfile

from app_profile import ProfileError, parse_profile
from app_profile.registry import PROJECT_ROOT, select_profile
from ingest.run_ingestion import DOMAINS, collect_chunks, domain_paths

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def profile_with(**sources):
    return parse_profile({
        "schema_version": 1, "app": {"id": "demo", "name": "Demo"},
        "sources": {"code": [{"repo": "acme/demo"}], **sources},
    })


print("\n-- the OrderFlow profile --")
profile = select_profile()
paths = domain_paths(profile)
check("the collections are docs and incidents", tuple(paths) == DOMAINS == ("docs", "incidents"))
check("docs resolve to knowledge-domains/docs", paths["docs"] == [PROJECT_ROOT / "knowledge-domains" / "docs"])
check("incidents resolve to knowledge-domains/incidents",
      paths["incidents"] == [PROJECT_ROOT / "knowledge-domains" / "incidents"])
counts = {d: len(collect_chunks(p)) for d, p in paths.items()}
check("chunk counts equal what Qdrant held before the change (docs 13, incidents 17)",
      counts == {"docs": 13, "incidents": 17}, str(counts))
check("every incident chunk comes from an INC-*.md file",
      all(c.source.startswith("INC-") for c in collect_chunks(paths["incidents"])))

print("\n-- several locations, files, and unsupported sources --")
with tempfile.TemporaryDirectory() as tmp:
    base = pathlib.Path(tmp)
    (base / "a").mkdir()
    (base / "b").mkdir()
    (base / "a" / "one.md").write_text("# One\n\nFirst folder text.\n", encoding="utf-8")
    (base / "b" / "two.md").write_text("# Two\n\nSecond folder text.\n", encoding="utf-8")
    (base / "b" / "ignored.txt").write_text("not markdown", encoding="utf-8")
    (base / "single.md").write_text("# Single\n\nA file given directly.\n", encoding="utf-8")

    demo = profile_with(docs=[{"path": "a"}, {"path": "b"}, {"path": "single.md"}])
    paths = domain_paths(demo, base)
    sources = [c.source for c in collect_chunks(paths["docs"])]
    check("several entries for one domain end up in one list, in order",
          sources == ["one.md", "two.md", "single.md"], str(sources))
    check("non-markdown files are ignored", "ignored.txt" not in sources)
    check("a domain the profile does not list is empty, not an error", paths["incidents"] == [])
    check("a missing folder yields no chunks rather than crashing",
          collect_chunks([base / "missing"]) == [])

    repo_docs = profile_with(docs=[{"repo": "acme/demo", "paths": ["docs/*.md"]}])
    try:
        domain_paths(repo_docs, base)
        check("a repository docs source is refused", False)
    except ProfileError as exc:
        check("a repository docs source is refused with a clear message",
              "not supported by ingestion yet" in str(exc) and "acme/demo" in str(exc), str(exc))

print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
raise SystemExit(1 if failures else 0)
