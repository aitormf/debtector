"""Review edge cases of the PR comment publisher (pr-diff, T7)."""

import importlib.util
import urllib.error
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "action_publish", _ROOT / "scripts" / "action_publish.py"
)
action_publish = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(action_publish)

MARKER = action_publish.MARKER
BOT = "github-actions[bot]"


class AuthoredApi:
    """Comments API whose comments carry their author, as GitHub's do."""

    def __init__(self, comments):
        self.comments = comments

    def list_comments(self):
        return list(self.comments)

    def create(self, body):
        self.comments.append({"id": 900, "body": body, "user": {"login": BOT}})

    def update(self, comment_id, body):
        next(c for c in self.comments if c["id"] == comment_id)["body"] = body


def test_a_users_comment_with_the_marker_is_never_overwritten(tmp_path: Path) -> None:
    user = {"id": 1, "body": f"{MARKER} quoting the bot", "user": {"login": "alice"}}
    bot = {"id": 2, "body": f"{MARKER}\nold", "user": {"login": BOT}}
    api = AuthoredApi([user, bot])

    action_publish.run(f"{MARKER}\nnew", 0, True, api, tmp_path / "s.md", author=BOT)

    assert user["body"] == f"{MARKER} quoting the bot"
    assert bot["body"] == f"{MARKER}\nnew"
    assert len(api.comments) == 2


@pytest.mark.parametrize(
    "error", [urllib.error.URLError("dns failure"), TimeoutError("timed out"), OSError("reset")]
)
def test_transport_failures_become_api_errors(monkeypatch, error) -> None:
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(action_publish.urllib.request, "urlopen", fail)
    api = action_publish.GitHubComments("https://api.github.com", "o/r", 1, "t")
    with pytest.raises(action_publish.ApiError):
        api.list_comments()


def test_network_failure_keeps_the_diff_exit_and_the_summary(tmp_path: Path, monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise urllib.error.URLError("dns failure")

    monkeypatch.setattr(action_publish.urllib.request, "urlopen", fail)
    api = action_publish.GitHubComments("https://api.github.com", "o/r", 1, "t")
    summary = tmp_path / "s.md"

    assert action_publish.run(f"{MARKER}\nbody", 0, False, api, summary, author=BOT) == 0
    assert "body" in summary.read_text(encoding="utf-8")


def test_workflow_cancels_superseded_runs_of_the_same_pr() -> None:
    workflow = yaml.safe_load((_ROOT / ".github" / "workflows" / "debtector.yml").read_text())
    concurrency = workflow["concurrency"]
    assert "pull_request.number" in concurrency["group"]
    assert concurrency["cancel-in-progress"] is True


def test_unknown_token_identity_matches_any_bot_but_never_a_person(tmp_path: Path) -> None:
    """A GitHub App token cannot read ``/user``: its comments come from ``<app>[bot]``."""
    user = {"id": 1, "body": f"{MARKER} quote", "user": {"login": "alice", "type": "User"}}
    app = {"id": 2, "body": f"{MARKER}\nold", "user": {"login": "my-app[bot]", "type": "Bot"}}
    api = AuthoredApi([user, app])

    action_publish.run(
        f"{MARKER}\nnew", 0, True, api, tmp_path / "s.md", author=action_publish.ANY_BOT
    )

    assert user["body"] == f"{MARKER} quote"
    assert app["body"] == f"{MARKER}\nnew"
    assert len(api.comments) == 2


def test_oversized_report_is_truncated_in_the_comment_but_whole_in_the_summary(
    tmp_path: Path,
) -> None:
    body = MARKER + "\n" + "| row |\n" * 20_000
    api = AuthoredApi([])
    summary = tmp_path / "s.md"

    action_publish.run(body, 0, True, api, summary, author=BOT)

    posted = api.comments[0]["body"]
    assert len(posted) <= 65_536
    assert posted.startswith(MARKER)
    assert "truncated" in posted
    assert summary.read_text(encoding="utf-8") == body


def test_a_crash_without_report_is_never_hidden(tmp_path: Path) -> None:
    """Exit 1 with no report is a crash (e.g. invalid config), not a severity violation."""
    api = AuthoredApi([])
    assert action_publish.run("", 1, False, api, tmp_path / "s.md", author=BOT) == 1
    assert api.comments == []
