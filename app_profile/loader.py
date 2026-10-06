"""
app_profile/loader.py — read one application profile (YAML), validate it
against appmind-app.schema.json, and return a frozen model with the schema
defaults applied.

The schema is the single source of truth for structure (unknown keys, patterns,
required keys, "exactly one location" for document sources). The models below
only carry the validated data, so a key is added in two places: the schema and
here. Errors name the file and the key path, so a typo is easy to find.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict

SCHEMA_PATH = pathlib.Path(__file__).with_name("appmind-app.schema.json")

# Platform default token when a source gives no `auth` (documented in the schema).
DEFAULT_SECRET = "GITHUB_TOKEN"


class ProfileError(Exception):
    """A profile could not be read or is invalid. The message names the file."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AppInfo(_Frozen):
    id: str
    name: str
    description: str | None = None
    owners: tuple[str, ...] = ()


class Scope(_Frozen):
    description: str | None = None
    # Component name -> words that mean it, in profile order (first match wins).
    aliases: dict[str, tuple[str, ...]] = {}


class CodeSource(_Frozen):
    repo: str
    ref: str = "main"
    source_root: str = "."
    exclude: tuple[str, ...] = ()
    secret: str = DEFAULT_SECRET  # NAME of the env var holding the token


class DocumentSource(_Frozen):
    # Exactly one of `path` or (`repo` + `paths`); the schema enforces it.
    path: str | None = None
    repo: str | None = None
    ref: str = "main"
    paths: tuple[str, ...] = ()
    secret: str = DEFAULT_SECRET


class Sources(_Frozen):
    code: tuple[CodeSource, ...]
    docs: tuple[DocumentSource, ...] = ()
    incidents: tuple[DocumentSource, ...] = ()


class AppProfile(_Frozen):
    schema_version: int
    app: AppInfo
    scope: Scope = Scope()
    sources: Sources


_validator: Draft202012Validator | None = None


def _schema_validator() -> Draft202012Validator:
    global _validator
    if _validator is None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        _validator = Draft202012Validator(schema)
    return _validator


def _key_path(error) -> str:
    return ".".join(str(part) for part in error.absolute_path) or "(top level)"


def _flatten_auth(entry: dict[str, Any]) -> dict[str, Any]:
    entry = dict(entry)
    auth = entry.pop("auth", None)
    if auth:
        entry["secret"] = auth["secret"]
    return entry


def parse_profile(data: Any, source: str = "<profile>") -> AppProfile:
    """Validate an already-loaded document and build the model."""
    if not isinstance(data, dict):
        raise ProfileError(f"{source}: a profile must be a mapping of keys, got {type(data).__name__}")

    errors = sorted(_schema_validator().iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        lines = "\n".join(f"  - {_key_path(e)}: {e.message}" for e in errors)
        raise ProfileError(f"{source}: invalid application profile\n{lines}")

    sources = data["sources"]
    return AppProfile(
        schema_version=data["schema_version"],
        app=data["app"],
        scope=data.get("scope", {}),
        sources={
            "code": [_flatten_auth(c) for c in sources["code"]],
            "docs": [_flatten_auth(d) for d in sources.get("docs", [])],
            "incidents": [_flatten_auth(d) for d in sources.get("incidents", [])],
        },
    )


def load_profile(path: str | pathlib.Path) -> AppProfile:
    """Read a profile file. Uses yaml.safe_load only (never constructs objects)."""
    path = pathlib.Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError(f"{path}: cannot read profile ({exc.strerror or exc})") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path}: not valid YAML: {exc}") from exc
    return parse_profile(data, source=str(path))
