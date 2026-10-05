"""Fetching: ref -> SHA, tarball download, and above all SAFE extraction.

Most checks use crafted in-memory tarballs and a mock HTTP transport, so they
need no network. A final live check runs against the registered repo only if
a GITHUB_TOKEN is available.
"""

from __future__ import annotations

import io
import pathlib
import tarfile
import tempfile

import httpx

from appmind_indexer import config, fetch
from appmind_indexer.registry import load_targets
from tests.helpers import Checker


def _tar(entries) -> bytes:
    """entries: (name, kind, data) with kind in {'dir', 'file', 'symlink'}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, kind, data in entries:
            info = tarfile.TarInfo(name)
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            elif kind == "file":
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = data.decode()
                tar.addfile(info)
    return buf.getvalue()


def _extract(entries, max_extracted=10_000):
    with tempfile.TemporaryDirectory() as tmp:
        dest = pathlib.Path(tmp)
        root = fetch._safe_extract(io.BytesIO(_tar(entries)), dest, max_extracted)
        files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
        contents = {f: (root / f).read_bytes() for f in files}
        return root.name, files, contents


def _raises(entries, **kwargs) -> bool:
    try:
        _extract(entries, **kwargs)
    except fetch.FetchError:
        return True
    return False


def main() -> int:
    check = Checker()

    check.section("safe extraction")
    top, files, contents = _extract([("o-r-abc", "dir", b""), ("o-r-abc/app", "dir", b""),
                                     ("o-r-abc/app/x.py", "file", b"x = 1\n")])
    check("a normal tarball extracts and returns the single top-level dir", top == "o-r-abc")
    check("file contents are preserved byte for byte", contents == {"app/x.py": b"x = 1\n"})
    check("path traversal is rejected", _raises([("o-r/../../evil.py", "file", b"x")]))
    check("an absolute path is rejected", _raises([("/etc/evil.py", "file", b"x")]))
    check("a backslash path is rejected", _raises([("o-r\\evil.py", "file", b"x")]))
    check("two top-level directories are rejected",
          _raises([("a", "dir", b""), ("b", "dir", b"")]))
    check("an oversized expansion is rejected",
          _raises([("o-r", "dir", b""), ("o-r/big.py", "file", b"x" * 10)], max_extracted=5))
    _, files, _ = _extract([("o-r", "dir", b""), ("o-r/link", "symlink", b"/etc/passwd"),
                            ("o-r/a.py", "file", b"x = 1\n")])
    check("a symlink entry is skipped, never materialized", files == ["a.py"], str(files))

    check.section("resolve_sha and download (mock transport)")
    good = _tar([("o-r-abc", "dir", b""), ("o-r-abc/a.py", "file", b"x = 1\n")])

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": "a" * 40})
        if path.endswith("/commits/missing"):
            return httpx.Response(404, json={"message": "Not Found"})
        if "/tarball/" in path:
            return httpx.Response(200, content=good)
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    check("resolve_sha returns the commit SHA", fetch.resolve_sha("o/r", "main", "tok-secret", client) == "a" * 40)
    try:
        fetch.resolve_sha("o/r", "missing", "tok-secret", client)
        message = ""
    except fetch.FetchError as exc:
        message = str(exc)
    check("a 404 raises FetchError that names the status", "404" in message, message)
    check("the error never contains the token", "tok-secret" not in message)
    with tempfile.TemporaryDirectory() as tmp:
        root = fetch.download_tarball("o/r", "a" * 40, "tok-secret", pathlib.Path(tmp), client=client)
        check("download_tarball extracts and returns the repo root", (root / "a.py").read_text() == "x = 1\n")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            fetch.download_tarball("o/r", "a" * 40, "tok", pathlib.Path(tmp), max_bytes=10, client=client)
        capped = False
    except fetch.FetchError:
        capped = True
    check("a download over the size cap is refused", capped)
    check("the client sends the token as a bearer header",
          fetch._client("tok").headers["authorization"] == "Bearer tok")

    check.section("live (skipped without GITHUB_TOKEN)")
    try:
        token = config.github_token()
    except RuntimeError:
        print("  SKIP  no GITHUB_TOKEN available")
    else:
        target = load_targets()[0]
        sha = fetch.resolve_sha(target.repo, target.ref, token)
        check("live: resolves to a 40-char SHA", len(sha) == 40, sha)
        with tempfile.TemporaryDirectory() as tmp:
            root = fetch.download_tarball(target.repo, sha, token, pathlib.Path(tmp))
            check("live: tarball extracts and contains Python files", any(root.rglob("*.py")))
    return check.finish()


if __name__ == "__main__":
    raise SystemExit(main())
