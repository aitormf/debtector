"""Tests of the PR comment publisher of the GitHub Action (D-0009)."""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "action_publish", Path(__file__).parent.parent / "scripts" / "action_publish.py"
)
action_publish = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(action_publish)

MARKER = "<!-- debtector-diff -->"
BODY = f"{MARKER}\n## debtector\n"


class FakeApi:
    """In-memory stand-in for the comments API of one PR."""

    def __init__(self, comments=None, read_only=False):
        self.comments = list(comments or [])
        self.read_only = read_only

    def list_comments(self):
        return list(self.comments)

    def create(self, body):
        if self.read_only:
            raise action_publish.ApiError(403)
        self.comments.append({"id": 100 + len(self.comments), "body": body})

    def update(self, comment_id, body):
        if self.read_only:
            raise action_publish.ApiError(403)
        for comment in self.comments:
            if comment["id"] == comment_id:
                comment["body"] = body


@pytest.fixture
def summary(tmp_path):
    return tmp_path / "summary.md"


def test_E27_first_push_creates_one_comment_with_the_marker(summary):
    api = FakeApi([{"id": 1, "body": "unrelated comment"}])

    action_publish.run(BODY, 0, True, api, summary)

    marked = [c for c in api.comments if c["body"].startswith(MARKER)]
    assert len(marked) == 1
    assert len(api.comments) == 2


def test_E28_second_push_updates_the_same_comment(summary):
    api = FakeApi()

    action_publish.run(BODY, 0, True, api, summary)
    action_publish.run(f"{MARKER}\nsecond\n", 0, True, api, summary)

    assert len(api.comments) == 1
    assert api.comments[0]["body"] == f"{MARKER}\nsecond\n"


def test_E29_read_only_token_warns_writes_summary_and_does_not_fail(summary, capsys):
    api = FakeApi(read_only=True)

    code = action_publish.run(BODY, 0, True, api, summary)

    assert code == 0
    assert api.comments == []
    assert summary.read_text() == BODY
    assert "::warning::" in capsys.readouterr().out


def test_E30_new_error_fails_the_job_after_publishing(summary):
    api = FakeApi()

    code = action_publish.run(BODY, 1, True, api, summary)

    assert code == 1
    assert len(api.comments) == 1
    assert summary.read_text() == BODY


def test_fail_on_error_false_keeps_the_job_green_on_exit_1(summary):
    assert action_publish.run(BODY, 1, False, FakeApi(), summary) == 0


def test_invalid_input_exit_2_is_never_hidden_and_posts_nothing(summary):
    api = FakeApi()

    assert action_publish.run("", 2, False, api, summary) == 2
    assert api.comments == []
