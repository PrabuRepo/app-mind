"""
app_profile/test_orderflow_profile.py — config/apps/orderflow.yaml reproduces
today's hardcoded values exactly, and profile selection works.

    python -m app_profile.test_orderflow_profile

The equality checks are the safety net for plan steps 3 to 5: each constant is
replaced by the profile only after this proves they agree, and each check is
deleted together with its constant. (DOMAIN_FOLDERS and TOPIC_DESCRIPTION are gone; the docs and
incidents folders are covered by ingest/test_ingestion_profile.py, the scope
text by guardrails/test_input_guardrail_profile.py.)
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import tomllib

from app_profile import ProfileError, load_profile
from app_profile.registry import PROFILES_DIR, PROJECT_ROOT, load_all, select_profile

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def raises(fn, *args) -> str | None:
    try:
        fn(*args)
    except ProfileError as exc:
        return str(exc)
    return None


profile = load_profile(PROFILES_DIR / "orderflow.yaml")

print("\n-- the OrderFlow profile equals today's hardcoded values --")
targets = tomllib.loads((PROJECT_ROOT / "indexer" / "targets.example.toml").read_text(encoding="utf-8"))["target"]
check("one code source, as in indexer/targets.example.toml", len(profile.sources.code) == len(targets) == 1)
code, target = profile.sources.code[0], targets[0]
check("repo equals targets.example.toml", code.repo == target["repo"])
check("ref equals targets.example.toml", code.ref == target["ref"])
check("source_root equals targets.example.toml", code.source_root == target["source_root"])
check("exclude equals targets.example.toml", list(code.exclude) == target["exclude"])

print("\n-- selection: config/apps/ and APPMIND_APP --")
check("the real config/apps/ holds exactly the OrderFlow profile",
      list(load_all(PROFILES_DIR)) == ["orderflow.yaml"])
check("a single profile is picked automatically", select_profile(PROFILES_DIR).app.id == "orderflow")
check("it can be named explicitly", select_profile(PROFILES_DIR, "orderflow").app.id == "orderflow")
msg = raises(select_profile, PROFILES_DIR, "nope")
check("an unknown id is an error naming what exists", msg is not None and "nope" in msg and "orderflow" in msg, str(msg))

with tempfile.TemporaryDirectory() as tmp:
    folder = pathlib.Path(tmp)
    shutil.copy(PROFILES_DIR / "orderflow.yaml", folder / "orderflow.yaml")
    other = (PROFILES_DIR / "orderflow.yaml").read_text(encoding="utf-8").replace("id: orderflow", "id: billing")
    (folder / "billing.yaml").write_text(other, encoding="utf-8")
    msg = raises(select_profile, folder)
    check("several profiles without APPMIND_APP is an error", msg is not None and "APPMIND_APP" in msg, str(msg))
    check("several profiles with an id selects that one", select_profile(folder, "billing").app.id == "billing")

    (folder / "billing.yaml").write_text(other.replace("id: billing", "id: orderflow"), encoding="utf-8")
    msg = raises(load_all, folder)
    check("a file name that differs from app.id is rejected", msg is not None and "must match" in msg, str(msg))

    (folder / "billing.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    msg = raises(load_all, folder)
    check("an invalid profile fails the whole set, naming the file", msg is not None and "billing.yaml" in msg, str(msg))

    empty = folder / "empty"
    empty.mkdir()
    msg = raises(select_profile, empty)
    check("an empty folder is an error", msg is not None and "no application profiles" in msg, str(msg))

print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
raise SystemExit(1 if failures else 0)
