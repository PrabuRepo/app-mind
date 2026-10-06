"""
app_profile/test_app_profile.py — the schema, the loader and the semantic checks.

    python -m app_profile.test_app_profile

No network, database or API key needed. The schema checks run every class of
mistake through the real loader, so a regression in either the schema file or
the loader fails here.
"""

from __future__ import annotations

import copy
import json
import pathlib
import tempfile

import yaml
from jsonschema import Draft202012Validator

from app_profile import ProfileError, load_profile, parse_profile
from app_profile.loader import SCHEMA_PATH
from app_profile.semantic import check_profile, check_unique_ids

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE = PROJECT_ROOT / "features" / "appmind-config" / "orderflow.example.yaml"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def error_of(doc) -> str | None:
    try:
        parse_profile(doc, source="test.yaml")
    except ProfileError as exc:
        return str(exc)
    return None


example = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
users_snippet = yaml.safe_load("""
schema_version: 1
app:
  id: orderflow
  name: OrderFlow
  owners: [team-orders]
sources:
  code:
    - repo: PrabuRepo/orderflow-app
      ref: main
      exclude: ["**/tests/**"]
      auth: { secret: GITHUB_TOKEN }
  docs:      [{ path: knowledge-domains/docs }]
  incidents: [{ path: knowledge-domains/incidents }]
""")
smallest = {"schema_version": 1, "app": {"id": "billing", "name": "Billing"},
            "sources": {"code": [{"repo": "acme/billing"}]}}


def mutated(fn):
    doc = copy.deepcopy(example)
    fn(doc)
    return doc


def rejected(label, fn):
    check(label, error_of(mutated(fn)) is not None, "no error raised")


def accepted(label, fn):
    check(label, error_of(mutated(fn)) is None, str(error_of(mutated(fn))))


print("\n-- the schema file and the documents that must pass --")
Draft202012Validator.check_schema(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
check("the schema is itself a valid JSON Schema (2020-12)", True)
check("the OrderFlow example validates", error_of(example) is None, str(error_of(example)))
check("the minimal snippet validates as-is", error_of(users_snippet) is None, str(error_of(users_snippet)))
check("the smallest profile (id, name, one repo) validates", error_of(smallest) is None, str(error_of(smallest)))

print("\n-- structure --")
rejected("an unknown top-level key (typo) is rejected", lambda d: d.update(scoop={"description": "x" * 50}))
rejected("an unknown nested key is rejected", lambda d: d["app"].update(nmae="x"))
rejected("a missing app is rejected", lambda d: d.pop("app"))
rejected("a missing app.name is rejected", lambda d: d["app"].pop("name"))
rejected("a missing code source is rejected", lambda d: d["sources"].pop("code"))
rejected("an empty code source list is rejected", lambda d: d["sources"].update(code=[]))
rejected("an unsupported schema_version is rejected", lambda d: d.update(schema_version=2))

print("\n-- options that are NOT implemented are not accepted (no silent no-ops) --")
for key in ("quality", "guardrails", "models", "retrieval", "question_types", "personas", "access", "storage"):
    rejected(f"the reserved key '{key}' is rejected", lambda d, k=key: d.update({k: {}}))
rejected("scope.glossary (still reserved) is rejected", lambda d: d["scope"].update(glossary={"A": "b"}))

print("\n-- values --")
rejected("a bad app id is rejected", lambda d: d["app"].update(id="Order Flow"))
rejected("a too-short scope description is rejected", lambda d: d["scope"].update(description="orders"))
rejected("a bad repo name is rejected", lambda d: d["sources"]["code"][0].update(repo="justaname"))
rejected("a source_root escaping the repo is rejected", lambda d: d["sources"]["code"][0].update(source_root="../etc"))
rejected("an absolute source_root is rejected", lambda d: d["sources"]["code"][0].update(source_root="/etc"))
rejected("an empty app description is rejected", lambda d: d["app"].update(description=""))
rejected("duplicate owners are rejected", lambda d: d["app"].update(owners=["a", "a"]))
rejected("a YAML boolean where a string is required is rejected (the 'no' pitfall)",
         lambda d: d["app"].update(name=False))

print("\n-- secrets are references, never values --")
rejected("auth holding a token-looking value is rejected",
         lambda d: d["sources"]["code"][0].update(auth={"secret": "ghp_abc123realtoken"}))
rejected("auth with a literal token field is rejected",
         lambda d: d["sources"]["code"][0].update(auth={"token": "ghp_abc123"}))
accepted("auth naming an env var is accepted",
         lambda d: d["sources"]["code"][0].update(auth={"secret": "GITHUB_TOKEN"}))

print("\n-- document sources: exactly one location --")
rejected("no location is rejected", lambda d: d["sources"]["docs"].append({"auth": {"secret": "X"}}))
rejected("two locations are rejected",
         lambda d: d["sources"]["docs"].append({"path": "docs", "repo": "o/r", "paths": ["*.md"]}))
rejected("a repo without paths is rejected", lambda d: d["sources"]["docs"].append({"repo": "o/r"}))
accepted("docs from a repository (repo + paths) are accepted",
         lambda d: d["sources"]["docs"].append({"repo": "acme/billing", "paths": ["docs/**/*.md"]}))

print("\n-- optional things really are optional --")
accepted("scope can be omitted", lambda d: d.pop("scope"))
accepted("scope: {} is accepted", lambda d: d.update(scope={}))
accepted("docs and incidents can be omitted", lambda d: (d["sources"].pop("docs"), d["sources"].pop("incidents")))
accepted("a monorepo subdirectory (source_root: src) is accepted",
         lambda d: d["sources"]["code"][0].update(source_root="src"))
accepted("several code repositories are accepted",
         lambda d: d["sources"]["code"].append({"repo": "acme/payments", "ref": "release"}))

print("\n-- the loader: defaults, shape, errors --")
profile = load_profile(EXAMPLE)
check("loads the example into a model", profile.app.id == "orderflow" and profile.app.name == "OrderFlow")
check("the app description comes through", profile.app.description == "an order-processing service")
code = profile.sources.code[0]
check("code source values come through",
      code.repo == "PrabuRepo/orderflow-app" and code.exclude == ("**/tests/**",))
check("defaults are applied: ref main, source_root '.', secret GITHUB_TOKEN",
      (code.ref, code.source_root, code.secret) == ("main", ".", "GITHUB_TOKEN"))
check("explicit auth overrides the default secret",
      parse_profile(mutated(lambda d: d["sources"]["code"][0].update(auth={"secret": "MY_TOKEN"}))).sources.code[0].secret
      == "MY_TOKEN")
check("docs and incidents paths come through",
      profile.sources.docs[0].path == "knowledge-domains/docs"
      and profile.sources.incidents[0].path == "knowledge-domains/incidents")
check("omitting scope gives no description", parse_profile(smallest).scope.description is None)
check("omitting scope gives no aliases", dict(parse_profile(smallest).scope.aliases) == {})
check("aliases come through as tuples, in profile order",
      list(profile.scope.aliases.items()) == [("PaymentClient", ("payment", "charge")),
                                              ("InventoryClient", ("invent", "stock", "oversell"))],
      str(profile.scope.aliases))
check("scope.description is kept", profile.scope.description is not None and "OrderFlow" in profile.scope.description)
try:
    profile.app.name = "x"  # type: ignore[misc]
    check("the model is frozen", False)
except Exception:
    check("the model is frozen", True)

msg = error_of(mutated(lambda d: d["sources"]["code"][0].update(repo="justaname")))
check("an error names the file and the key path", msg is not None and "test.yaml" in msg and "sources.code.0.repo" in msg, str(msg))
msg = error_of(mutated(lambda d: (d["app"].update(nmae="x"), d["sources"]["code"].clear())))
check("all problems are reported together, not just the first",
      msg is not None and "app" in msg and "sources.code" in msg, str(msg))
check("a non-mapping document is rejected clearly", "mapping" in (error_of(["a", "b"]) or ""))

with tempfile.TemporaryDirectory() as tmp:
    tmp_dir = pathlib.Path(tmp)
    try:
        load_profile(tmp_dir / "missing.yaml")
        check("a missing file raises ProfileError", False)
    except ProfileError as exc:
        check("a missing file raises ProfileError naming the file", "missing.yaml" in str(exc))
    bad = tmp_dir / "bad.yaml"
    bad.write_text("app: [unclosed", encoding="utf-8")
    try:
        load_profile(bad)
        check("broken YAML raises ProfileError", False)
    except ProfileError as exc:
        check("broken YAML raises ProfileError naming the file", "bad.yaml" in str(exc) and "YAML" in str(exc))
    unsafe = tmp_dir / "unsafe.yaml"
    unsafe.write_text("schema_version: !!python/object/apply:os.getcwd []\n", encoding="utf-8")
    try:
        load_profile(unsafe)
        check("a YAML object tag is refused (safe_load only)", False)
    except ProfileError:
        check("a YAML object tag is refused (safe_load only)", True)

print("\n-- semantic checks --")
env_ok = {"GITHUB_TOKEN": "x"}
check("a valid profile passes with its secret set and paths present",
      check_profile(profile, PROJECT_ROOT, env_ok) == [], str(check_profile(profile, PROJECT_ROOT, env_ok)))
problems = check_profile(profile, PROJECT_ROOT, {})
check("an unset secret is reported", any("GITHUB_TOKEN" in p for p in problems), str(problems))
problems = check_profile(profile, PROJECT_ROOT / "nowhere", env_ok)
check("a missing docs/incidents path is reported",
      any("knowledge-domains/docs" in p for p in problems) and any("knowledge-domains/incidents" in p for p in problems),
      str(problems))
repo_docs = parse_profile(mutated(lambda d: d["sources"]["docs"].append(
    {"repo": "acme/billing", "paths": ["docs/*.md"], "auth": {"secret": "BILLING_TOKEN"}})))
check("a repo-based docs source needs its secret, not a local path",
      any("BILLING_TOKEN" in p for p in check_profile(repo_docs, PROJECT_ROOT, env_ok)))
check("matching file name and unique ids pass", check_unique_ids([("orderflow.yaml", profile)]) == [])
check("a file name that differs from app.id is reported",
      any("must match" in p for p in check_unique_ids([("other.yaml", profile)])))
check("a duplicate app.id is reported",
      any("already used" in p for p in check_unique_ids([("orderflow.yaml", profile), ("orderflow.yaml", profile)])))

print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
raise SystemExit(1 if failures else 0)
