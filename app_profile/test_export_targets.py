"""
app_profile/test_export_targets.py — the profile-to-indexer hand-off.

    python -m app_profile.test_export_targets

No network or database. The indexer is never imported (the boundary test
forbids it); the generated file is checked as plain TOML data against what the
indexer's registry accepts (see indexer/appmind_indexer/registry.py).
"""

from __future__ import annotations

import pathlib
import tempfile
import tomllib

from app_profile import ProfileError, parse_profile
from app_profile.export_targets import DEFAULT_OUT, main, render_targets
from app_profile.registry import PROJECT_ROOT, select_profile

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def profile_with(code: list[dict]):
    return parse_profile({"schema_version": 1, "app": {"id": "demo", "name": "Demo"}, "sources": {"code": code}})


print("\n-- the OrderFlow profile --")
text = render_targets(select_profile())
data = tomllib.loads(text)
example = tomllib.loads((PROJECT_ROOT / "indexer" / "targets.example.toml").read_text(encoding="utf-8"))
check("it is valid TOML", "target" in data)
check("its targets equal the indexer's example registry (the old committed targets.toml)",
      data["target"] == example["target"], str(data))
check("it says it is generated and where from", "GENERATED" in text and "config/apps/orderflow.yaml" in text)
check("it holds identifiers only, no secret values", "token" not in text.lower() and "ghp_" not in text)

print("\n-- other profiles --")
multi = profile_with([
    {"repo": "acme/billing", "ref": "release", "source_root": "src", "exclude": ["**/tests/**", 'a"b']},
    {"repo": "acme/payments"},
])
targets = tomllib.loads(render_targets(multi))["target"]
check("several code sources become several targets, in order", [t["repo"] for t in targets] == ["acme/billing", "acme/payments"])
check("ref, source_root and exclude come through, with defaults applied",
      targets[0] == {"repo": "acme/billing", "ref": "release", "source_root": "src", "exclude": ["**/tests/**", 'a"b']}
      and targets[1] == {"repo": "acme/payments", "ref": "main", "source_root": ".", "exclude": []}, str(targets))
try:
    render_targets(profile_with([{"repo": "acme/billing", "auth": {"secret": "BILLING_TOKEN"}}]))
    check("a per-source secret the indexer would ignore is refused", False)
except ProfileError as exc:
    check("a per-source secret the indexer would ignore is refused, not silently dropped",
          "BILLING_TOKEN" in str(exc) and "not supported by the indexer" in str(exc), str(exc))
check("an explicit default secret is fine", len(tomllib.loads(render_targets(
    profile_with([{"repo": "acme/billing", "auth": {"secret": "GITHUB_TOKEN"}}])))["target"]) == 1)

print("\n-- the command --")
with tempfile.TemporaryDirectory() as tmp:
    out = pathlib.Path(tmp) / "nested" / "targets.toml"
    check("writes the file (creating folders) and exits 0", main(["--out", str(out)]) == 0 and out.is_file())
    check("the file equals the rendered text", out.read_text(encoding="utf-8") == text)
    check("it uses LF line endings", b"\r" not in out.read_bytes())
check("the default output is indexer/targets.toml, which git ignores",
      DEFAULT_OUT == PROJECT_ROOT / "indexer" / "targets.toml"
      and "indexer/targets.toml" in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8"))

print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
raise SystemExit(1 if failures else 0)
