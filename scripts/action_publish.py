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
# Publisher whose login is unknown (``GITHUB_TOKEN`` or a GitHub App token cannot read
# ``/user``): its comments are authored by some ``<name>[bot]``, never by a person.
ANY_BOT = "<any bot>"
# GitHub rejects comments longer than this (HTTP 422).
MAX_COMMENT = 65_536
_TRUNCATED = "\n\n…report truncated: the full diff is in the job summary of this run.\n"


class ApiError(Exception):
    """A GitHub API request failed (``status`` is the HTTP code, 0 for network errors)."""

    def __init__(self, status: int, reason: str = "") -> None:
        super().__init__(f"HTTP {status}" if status else f"network error: {reason}")
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
        except (urllib.error.URLError, OSError) as e:  # DNS, refused, reset, timeout
            raise ApiError(0, str(e)) from e

    def login(self) -> str:
        """Login of the token's owner (a PAT), or :data:`ANY_BOT` if the token is a bot's."""
        try:
            return self._request("GET", self._url.rsplit("/repos/", 1)[0] + "/user")["login"]
        except ApiError:
            return ANY_BOT

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


def find_comment_id(comments: list[dict], author: str | None = None) -> int | None:
    """Return the id of the publisher's comment that starts with the marker, if any.

    Args:
        comments: Comments of the PR.
        author: Login that publishes the report, or :data:`ANY_BOT` for a bot token. A
            comment with the marker written by someone else (e.g. a person quoting it) is
            never picked. ``None`` accepts any author.
    """
    for comment in comments:
        if not (comment.get("body") or "").startswith(MARKER):
            continue
        user = comment.get("user") or {}
        if (
            author is None
            or (author == ANY_BOT and user.get("type") == "Bot")
            or user.get("login") == author
        ):
            return comment["id"]
    return None


def bounded(body: str) -> str:
    """Cut *body* to GitHub's comment limit, saying so; the marker stays at the start."""
    if len(body) <= MAX_COMMENT:
        return body
    return body[: MAX_COMMENT - len(_TRUNCATED)] + _TRUNCATED


def publish(body: str, api: CommentsApi, author: str | None = None) -> None:
    """Create the comment, or update the publisher's one that already has the marker."""
    body = bounded(body)
    existing = find_comment_id(api.list_comments(), author)
    if existing is None:
        api.create(body)
    else:
        api.update(existing, body)


def run(
    body: str,
    diff_exit: int,
    fail_on_error: bool,
    api: CommentsApi,
    summary: Path,
    author: str | None = None,
) -> int:
    """Publish the diff and return the exit code the job must finish with.

    Args:
        body: Markdown produced by ``debtector diff --format markdown``.
        diff_exit: Exit code of that command.
        fail_on_error: Whether exit 1 (new ``error`` severity) must fail the job.
        api: Where the comment is published.
        summary: Path of ``$GITHUB_STEP_SUMMARY``.
        author: Login that publishes the comment (see :func:`find_comment_id`).

    Returns:
        ``diff_exit``, except that exit 1 becomes 0 without ``fail_on_error``.
        Exit 2 (invalid input) is never hidden, and nothing is posted for it.
    """
    if body.strip():
        with summary.open("a", encoding="utf-8") as f:
            f.write(body)
        try:
            publish(body, api, author)
        except ApiError as e:
            # Forks get a read-only token, or the network fails: the summary is then
            # the only output, and the diff's own exit code still decides the job.
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
    author = api.login()
    return run(body, args.diff_exit, args.fail_on_error == "true", api, summary, author)


if __name__ == "__main__":
    sys.exit(main())
