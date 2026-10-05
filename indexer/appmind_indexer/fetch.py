"""
appmind_indexer/fetch.py — get one repository snapshot onto local disk.

Two steps: resolve a ref (branch/tag) to an immutable commit SHA, then
download that exact commit as a tarball and extract it safely into a
directory the caller owns (a TemporaryDirectory, deleted when indexing ends).

Plain GitHub REST, not MCP: this is a batch job where one tarball request
beats many per-file tool calls, and the token's own read-only scope is still
what enforces "no writes". Nothing here ever logs the token.
"""

from __future__ import annotations

import pathlib
import shutil
import tarfile
import tempfile

import httpx

API = "https://api.github.com"
TIMEOUT_S = 60.0
MAX_TARBALL_BYTES = 100 * 1024 * 1024      # compressed download cap
MAX_EXTRACTED_BYTES = 500 * 1024 * 1024    # uncompressed cap (zip-bomb guard)


class FetchError(RuntimeError):
    pass


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        follow_redirects=True,   # the tarball endpoint redirects to a pre-signed URL
        timeout=TIMEOUT_S,
    )


def _explain(status: int, body: str, what: str) -> str:
    hint = {
        401: "the token was rejected",
        403: "the token lacks access or a rate limit was hit",
        404: "the repo/ref was not found, or the token cannot see it",
    }.get(status, "unexpected response")
    return f"GitHub {what} failed: HTTP {status} ({hint}): {body[:200]}"


def resolve_sha(repo: str, ref: str, token: str, client: httpx.Client | None = None) -> str:
    """Resolve a branch/tag/SHA to the full commit SHA it points at right now."""
    owns_client = client is None
    client = client or _client(token)
    try:
        r = client.get(f"{API}/repos/{repo}/commits/{ref}")
        if r.status_code != 200:
            raise FetchError(_explain(r.status_code, r.text, f"resolving {repo}@{ref}"))
        return r.json()["sha"]
    finally:
        if owns_client:
            client.close()


def _safe_extract(fileobj, dest: pathlib.Path, max_extracted: int) -> pathlib.Path:
    """Extract a gzipped tarball into `dest`, refusing anything that could
    write outside it. Only regular files and directories are materialized;
    symlinks, hardlinks and device nodes are skipped. Returns the single
    top-level directory GitHub wraps every tarball in."""
    dest = dest.resolve()
    total = 0
    tops: set[str] = set()
    with tarfile.open(fileobj=fileobj, mode="r:gz") as tar:
        for member in tar:
            name = member.name
            parts = pathlib.PurePosixPath(name).parts
            if not parts or pathlib.PurePosixPath(name).is_absolute() or ".." in parts or "\\" in name:
                raise FetchError(f"unsafe path in tarball: {name!r}")
            target = (dest / pathlib.PurePosixPath(*parts)).resolve()
            if dest != target and dest not in target.parents:
                raise FetchError(f"tarball entry escapes the target directory: {name!r}")
            tops.add(parts[0])
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isreg():
                total += member.size
                if total > max_extracted:
                    raise FetchError(f"tarball expands beyond {max_extracted} bytes; refusing")
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(member)
                with open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
            # anything else (symlink, hardlink, device): deliberately skipped
    if len(tops) != 1:
        raise FetchError(f"expected exactly one top-level directory in the tarball, found {sorted(tops)}")
    return dest / next(iter(tops))


def download_tarball(
    repo: str,
    sha: str,
    token: str,
    dest: pathlib.Path,
    *,
    max_bytes: int = MAX_TARBALL_BYTES,
    max_extracted: int = MAX_EXTRACTED_BYTES,
    client: httpx.Client | None = None,
) -> pathlib.Path:
    """Download commit `sha` of `repo` and extract it under `dest`. Returns the
    extracted repository root (the single directory inside the tarball)."""
    owns_client = client is None
    client = client or _client(token)
    try:
        with tempfile.TemporaryFile() as buf:
            with client.stream("GET", f"{API}/repos/{repo}/tarball/{sha}") as r:
                if r.status_code != 200:
                    r.read()
                    raise FetchError(_explain(r.status_code, r.text, f"downloading {repo}@{sha[:7]}"))
                total = 0
                for chunk in r.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise FetchError(f"tarball exceeds {max_bytes} bytes; refusing")
                    buf.write(chunk)
            buf.seek(0)
            return _safe_extract(buf, dest, max_extracted)
    finally:
        if owns_client:
            client.close()
