#!/usr/bin/env python3
"""Publish the debtector diff of a PR as a single comment (D-0009).

Dependency-free on purpose: the composite Action runs it with the runner's
``python3``. The comment is found by its hidden marker, so every push updates
it instead of adding a new one. The diff always goes to the job summary too.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

MARKER = "<!-- debtector-diff -->"


class ApiError(Exception):
    """The GitHub API refused a request (``status`` is the HTTP code)."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class CommentsApi(Protocol):
    """The three operations the publisher needs on the comments of one PR."""

    def list_comments(self) -> list[dict]: ...
    def create(self, body: str) -> None: ...
    def update(self, comment_id: int, body: str) -> None: ...


class GitHubComments:
    """REST client for the issue comments of one PR."""

    def __init__(self, api_url: str, repo: str, number: int, token: str) -> None:
        if not api_url.startswith("https://"):
            raise ValueError("GITHUB_API_URL must be https")
        self._url = f"{api_url}/repos/{repo}/issues"
        self._number = number
        self._token = token

    def _request(self, method: str, url: str, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(  # noqa: S310
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raise ApiError(e.code) from e

    def list_comments(self) -> list[dict]:
        """Return every comment of the PR, following the pagination."""
        comments: list[dict] = []
        page = 1
        while True:
            chunk = self._request(
                "GET", f"{self._url}/{self._number}/comments?per_page=100&page={page}"
            )
            comments += chunk
            if len(chunk) < 100:
                return comments
            page += 1

    def create(self, body: str) -> None:
        """Create a new comment."""
        self._request("POST", f"{self._url}/{self._number}/comments", {"body": body})

    def update(self, comment_id: int, body: str) -> None:
        """Replace the body of an existing comment."""
        self._request("PATCH", f"{self._url}/comments/{comment_id}", {"body": body})


def find_comment_id(comments: list[dict]) -> int | None:
    """Return the id of the comment that starts with the marker, if any."""
    for comment in comments:
        if (comment.get("body") or "").startswith(MARKER):
            return comment["id"]
    return None


def publish(body: str, api: CommentsApi) -> None:
    """Create the comment, or update the one that already has the marker."""
    existing = find_comment_id(api.list_comments())
    if existing is None:
        api.create(body)
    else:
        api.update(existing, body)


def run(body: str, diff_exit: int, fail_on_error: bool, api: CommentsApi, summary: Path) -> int:
    """Publish the diff and return the exit code the job must finish with.

    Args:
        body: Markdown produced by ``debtector diff --format markdown``.
        diff_exit: Exit code of that command.
        fail_on_error: Whether exit 1 (new ``error`` severity) must fail the job.
        api: Where the comment is published.
        summary: Path of ``$GITHUB_STEP_SUMMARY``.

    Returns:
        ``diff_exit``, except that exit 1 becomes 0 without ``fail_on_error``.
        Exit 2 (invalid input) is never hidden, and nothing is posted for it.
    """
    if body.strip():
        with summary.open("a", encoding="utf-8") as f:
            f.write(body)
        try:
            publish(body, api)
        except ApiError as e:
            # Forks get a read-only token: the summary is then the only output.
            print(f"::warning::debtector could not comment on the PR ({e}); see the job summary")
    if diff_exit == 1 and not fail_on_error:
        return 0
    return diff_exit


def main() -> int:
    """Read the Action environment and run :func:`run`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", type=Path, required=True)
    parser.add_argument("--diff-exit", type=int, required=True)
    parser.add_argument("--fail-on-error", choices=["true", "false"], default="true")
    args = parser.parse_args()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    api = GitHubComments(
        os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        os.environ["GITHUB_REPOSITORY"],
        event["pull_request"]["number"],
        os.environ["GITHUB_TOKEN"],
    )
    summary = Path(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull))
    body = args.body_file.read_text(encoding="utf-8")
    return run(body, args.diff_exit, args.fail_on_error == "true", api, summary)


if __name__ == "__main__":
    sys.exit(main())
