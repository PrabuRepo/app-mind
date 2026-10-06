"""Registry (targets.toml) loading and validation."""

from __future__ import annotations

import tempfile
import pathlib

from appmind_indexer.registry import RegistryError, load_targets
from tests.helpers import EXAMPLE_TARGETS, Checker


def _load_text(text: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "targets.toml"
        path.write_text(text, encoding="utf-8")
        return load_targets(path)


def _raises(text: str) -> bool:
    try:
        _load_text(text)
    except RegistryError:
        return True
    return False


def main() -> int:
    check = Checker()

    check.section("the shipped targets.example.toml")
    targets = load_targets(EXAMPLE_TARGETS)
    check("has at least one target", len(targets) >= 1)
    check("repo is owner/name", "/" in targets[0].repo, targets[0].repo)

    check.section("defaults and parsing")
    t = _load_text('[[target]]\nrepo = "o/r"\n')[0]
    check("ref defaults to main", t.ref == "main")
    check("source_root defaults to '.'", t.source_root == ".")
    check("exclude defaults to empty", t.exclude == ())
    t = _load_text('[[target]]\nrepo = "o/r"\nref = "v1"\nsource_root = "src"\nexclude = ["**/x/**"]\n')[0]
    check("explicit fields parsed", (t.ref, t.source_root, t.exclude) == ("v1", "src", ("**/x/**",)))

    check.section("validation")
    check("rejects a repo that is not owner/name", _raises('[[target]]\nrepo = "justaname"\n'))
    check("rejects '..' in source_root", _raises('[[target]]\nrepo = "o/r"\nsource_root = "../x"\n'))
    check("rejects an absolute source_root", _raises('[[target]]\nrepo = "o/r"\nsource_root = "/etc"\n'))
    check("rejects a file with no targets", _raises("# nothing here\n"))
    return check.finish()


if __name__ == "__main__":
    raise SystemExit(main())
