"""
mcp_clients/test_github_client.py — tests mcp_clients/github_client.py against
the REAL remote GitHub MCP server (per CLAUDE.md: real connections, not
mocks) and the real hosted orderflow-app repo.

    python -m mcp_clients.test_github_client
"""

from __future__ import annotations

from unittest.mock import patch

from mcp_clients import github_client

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def test_fetch_single_file() -> None:
    print("== fetch_source_files: one real file ==")
    result = github_client.fetch_source_files(["app/payment_client.py"])
    check("no errors", not result.errors, str(result.errors))
    check("one chunk returned", len(result.chunks) == 1, str(len(result.chunks)))
    if result.chunks:
        chunk = result.chunks[0]
        check("collection is 'code'", chunk.collection == "code")
        check("source is 'github:get_file_contents'", chunk.source == "github:get_file_contents")
        check("location is the requested path", chunk.location == "app/payment_client.py")
        check("real content, not the status message", "class PaymentClient" in chunk.text, chunk.text[:80])
        check("contains the planted-bug marker", "idempotency" in chunk.text.lower())


def test_fetch_multiple_files_and_cap() -> None:
    print("== fetch_source_files: multiple files, capped at MAX_FILES ==")
    all_files = ["app/api.py", "app/order_service.py", "app/payment_client.py",
                 "app/inventory_client.py", "app/notification_service.py"]
    result = github_client.fetch_source_files(all_files)
    check(f"capped at MAX_FILES={github_client.MAX_FILES}", len(result.chunks) == github_client.MAX_FILES,
          str(len(result.chunks)))
    locations = {c.location for c in result.chunks}
    check("fetched exactly the first MAX_FILES paths, in order",
          locations == set(all_files[:github_client.MAX_FILES]), str(locations))


def test_missing_file_is_an_error_not_a_crash() -> None:
    print("== fetch_source_files: a path that doesn't exist ==")
    result = github_client.fetch_source_files(["app/does_not_exist.py"])
    check("no chunk for the missing file", len(result.chunks) == 0)
    check("recorded as an error, not raised", len(result.errors) == 1, str(result.errors))


def test_degrades_on_bad_token() -> None:
    print("== fetch_source_files raises on auth failure (retrieval.py is the one that catches it) ==")
    with patch.object(github_client, "_config", return_value=("github_pat_intentionally_invalid", "PrabuRepo/orderflow-app")):
        try:
            github_client.fetch_source_files(["app/payment_client.py"])
            check("raises rather than silently succeeding", False)
        except Exception as exc:
            check("raises rather than silently succeeding", True, f"{type(exc).__name__}")


if __name__ == "__main__":
    test_fetch_single_file()
    test_fetch_multiple_files_and_cap()
    test_missing_file_is_an_error_not_a_crash()
    test_degrades_on_bad_token()
    print(f"\n{len(failures)} failure(s)" if failures else "\nAll checks passed.")
    raise SystemExit(1 if failures else 0)
