"""Tests for ``test_paths`` config and the skipped testRisk section of ``audit``."""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
from pathlib import Path
from types import SimpleNamespace

import pytest

from debtector.cli import _get_store, cmd_audit, cmd_index
from debtector.config import load_config
from debtector.logging import configure_logging
from debtector.metrics import compute_metrics

_HIGH_CE_MODULE = "".join(f"import mod{i}\n" for i in range(12)) + (
    "\n\ndef risky():\n    return 1\n"
)

_TEST_MODULE = "from service import helper\n\n\ndef test_helper():\n    assert helper() == 1\n"


def _make_project(
    root: Path,
    *,
    with_tests: bool,
    tests_dir: str = "tests",
    toml: str | None = None,
) -> Path:
    """Create ``src/`` (+ optionally ``tests/``) under *root*."""
    (root / "src").mkdir(parents=True)
    (root / "src" / "service.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "src" / "risky.py").write_text(_HIGH_CE_MODULE, encoding="utf-8")
    if with_tests:
        (root / tests_dir).mkdir(parents=True)
        (root / tests_dir / "test_service.py").write_text(_TEST_MODULE, encoding="utf-8")
    if toml is not None:
        (root / "debtector.toml").write_text(toml, encoding="utf-8")
    _git_commit_all(root)
    return root


def _git_commit_all(root: Path) -> None:
    """Initialise a git repo with one commit (audit reads churn and blame)."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=root, check=True, env=env)  # nosec B603 B607


def _index(project: Path, path: str) -> None:
    cmd_index(SimpleNamespace(project=str(project), path=str(project / path), json=True))


def _audit_json(project: Path, capsys: pytest.CaptureFixture[str]) -> dict:
    capsys.readouterr()
    cmd_audit(SimpleNamespace(project=str(project), top_n=10, full=True, json=True))
    return json.loads(capsys.readouterr().out)


class TestTestPathsConfig:
    """``test_paths`` parsing and default."""

    def test_default_is_empty(self, tmp_path: Path) -> None:
        assert load_config(tmp_path).test_paths == []

    def test_parsed_from_toml(self, tmp_path: Path) -> None:
        (tmp_path / "debtector.toml").write_text('test_paths = ["tests", "e2e"]\n')
        assert load_config(tmp_path).test_paths == ["tests", "e2e"]

    def test_must_be_list_of_strings(self, tmp_path: Path) -> None:
        (tmp_path / "debtector.toml").write_text('test_paths = "tests"\n')
        with pytest.raises(ValueError, match="test_paths"):
            load_config(tmp_path)


class TestIndexingTestPaths:
    """Tests outside the indexed directory are indexed and produce COVERS."""

    def test_covers_edges_from_external_tests(self, tmp_path: Path) -> None:
        _make_project(tmp_path, with_tests=True, toml='test_paths = ["tests"]\n')
        _index(tmp_path, "src")
        store = _get_store(str(tmp_path))
        try:
            covers = store._conn.execute(
                "SELECT source_qualified, target_qualified FROM edges WHERE kind = 'COVERS'"
            ).fetchall()
            uncovered = {s.file_path for s in store.get_uncovered_symbols()}
        finally:
            store.close()
        assert any(c["target_qualified"].endswith("service.py::helper") for c in covers)
        assert "service.py" not in uncovered
        assert "risky.py" in uncovered

    def test_external_tests_not_counted_as_modules(self, tmp_path: Path) -> None:
        _make_project(tmp_path, with_tests=True, toml='test_paths = ["tests"]\n')
        _index(tmp_path, "src")
        store = _get_store(str(tmp_path))
        try:
            metrics = compute_metrics(store)
        finally:
            store.close()
        assert {m.file_path for m in metrics} == {"service.py", "risky.py"}
        # the test's import of ``service`` does not raise its Ca
        assert {m.file_path: m.fan_in for m in metrics}["service.py"] == 0

    def test_without_test_paths_tests_are_not_indexed(self, tmp_path: Path) -> None:
        _make_project(tmp_path, with_tests=True)
        _index(tmp_path, "src")
        store = _get_store(str(tmp_path))
        try:
            assert all(not p.startswith("..") for p in store.get_all_files())
        finally:
            store.close()

    def test_reindex_keeps_external_tests(self, tmp_path: Path) -> None:
        _make_project(tmp_path, with_tests=True, toml='test_paths = ["tests"]\n')
        _index(tmp_path, "src")
        _index(tmp_path, "src")
        store = _get_store(str(tmp_path))
        try:
            assert any("test_service.py" in p for p in store.get_all_files())
        finally:
            store.close()

    def test_test_path_outside_conventions_is_test(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path, with_tests=True, tests_dir="checks", toml='test_paths = ["checks"]\n'
        )
        (tmp_path / "checks" / "test_service.py").rename(tmp_path / "checks" / "verify.py")
        _index(tmp_path, ".")
        store = _get_store(str(tmp_path))
        try:
            uncovered = {s.file_path for s in store.get_uncovered_symbols()}
            assert not any(p.endswith("verify.py") for p in uncovered)
            assert store.count_test_files() == 1
        finally:
            store.close()


class TestAuditTestRisk:
    """testRisk section: skipped without tests, ``ok`` with tests."""

    def test_no_tests_skips_testrisk_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _make_project(tmp_path, with_tests=False)
        _index(tmp_path, "src")
        tr = _audit_json(tmp_path, capsys)["testRisk"]
        assert tr["status"] == "skipped"
        assert tr["reason"] == "no_tests_found"
        assert tr["untested_high_coupling"] == []
        assert tr["untested_hotspots"] == []
        assert "critical_knowledge_concentration" in tr

    def test_no_tests_not_in_score(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Same sources, with and without tests: the "untested high-coupling"
        # finding of risky.py only costs score when tests exist.
        skipped_root = _make_project(tmp_path / "a", with_tests=False)
        _index(skipped_root, "src")
        skipped = _audit_json(skipped_root, capsys)["summary"]["health_score"]
        ok_root = _make_project(tmp_path / "b", with_tests=True, toml='test_paths = ["tests"]\n')
        _index(ok_root, "src")
        scored = _audit_json(ok_root, capsys)["summary"]["health_score"]
        assert skipped > scored

    def test_no_tests_human_warning_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _make_project(tmp_path, with_tests=False)
        _index(tmp_path, "src")
        capsys.readouterr()
        cmd_audit(SimpleNamespace(project=str(tmp_path), top_n=10, full=False, json=False))
        captured = capsys.readouterr()
        assert "No se han encontrado tests" in captured.err
        assert "test_paths" in captured.err
        assert "test_paths" not in captured.out

    def test_with_tests_status_ok_and_findings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _make_project(tmp_path, with_tests=True)
        _index(tmp_path, ".")
        tr = _audit_json(tmp_path, capsys)["testRisk"]
        assert tr["status"] == "ok"
        assert "reason" not in tr
        assert any(p.endswith("risky.py") for p in tr["untested_high_coupling"])

    def test_with_test_paths_status_ok(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _make_project(tmp_path, with_tests=True, toml='test_paths = ["tests"]\n')
        _index(tmp_path, "src")
        tr = _audit_json(tmp_path, capsys)["testRisk"]
        assert tr["status"] == "ok"
        assert tr["untested_high_coupling"] == ["risky.py"]

    def test_summary_excludes_external_tests(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _make_project(tmp_path, with_tests=True, toml='test_paths = ["tests"]\n')
        _index(tmp_path, "src")
        out = _audit_json(tmp_path, capsys)
        assert out["summary"]["modules"] == 2
        assert {c["file_path"] for c in out["coupling"]} == {"service.py", "risky.py"}

    def test_no_warning_when_tests_exist(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _make_project(tmp_path, with_tests=True, toml='test_paths = ["tests"]\n')
        _index(tmp_path, "src")
        capsys.readouterr()
        cmd_audit(SimpleNamespace(project=str(tmp_path), top_n=10, full=False, json=False))
        assert "No se han encontrado tests" not in capsys.readouterr().err


@pytest.fixture(autouse=True)
def _file_logging(tmp_path: Path) -> None:
    """Route logs to ``.debtector/debtector.log`` as the real CLI does."""
    configure_logging(project=str(tmp_path))


class TestNonConventionalTestDir:
    """Parsers must classify tests like the store does (conventions + test_paths)."""

    def _project(self, root: Path, toml: str) -> Path:
        _make_project(root, with_tests=False, toml=toml)
        (root / "checks").mkdir()
        (root / "checks" / "verify.py").write_text(
            "from service import helper\n\n\ndef check_helper():\n    assert helper() == 1\n",
            encoding="utf-8",
        )
        return root

    def test_covers_from_non_conventional_dir(self, tmp_path: Path) -> None:
        self._project(tmp_path, 'test_paths = ["checks"]\n')
        _index(tmp_path, ".")
        store = _get_store(str(tmp_path))
        try:
            covered = store._conn.execute(
                "SELECT target_qualified FROM edges WHERE kind = 'COVERS'"
            ).fetchall()
            uncovered = {s.qualified_name for s in store.get_uncovered_symbols()}
        finally:
            store.close()
        assert any(c["target_qualified"].endswith("service.py::helper") for c in covered)
        assert not any(q.endswith("service.py::helper") for q in uncovered)

    def test_changing_test_paths_reparses_indexed_files(self, tmp_path: Path) -> None:
        self._project(tmp_path, "")
        _index(tmp_path, ".")
        (tmp_path / "debtector.toml").write_text('test_paths = ["checks"]\n')
        _index(tmp_path, ".")
        store = _get_store(str(tmp_path))
        try:
            n = store._conn.execute("SELECT COUNT(*) FROM edges WHERE kind='COVERS'").fetchone()[0]
        finally:
            store.close()
        assert n >= 1

    def test_fresh_index_of_subdir_uses_new_root_for_prefixes(self, tmp_path: Path) -> None:
        _make_project(tmp_path, with_tests=False, toml='test_paths = ["src/checks"]\n')
        (tmp_path / "src" / "checks").mkdir()
        (tmp_path / "src" / "checks" / "verify.py").write_text(
            "from service import helper\n\n\ndef check_helper():\n    assert helper() == 1\n",
            encoding="utf-8",
        )
        _index(tmp_path, "src")
        store = _get_store(str(tmp_path))
        try:
            assert store.test_prefixes == ["checks/"]
            n = store._conn.execute("SELECT COUNT(*) FROM edges WHERE kind='COVERS'").fetchone()[0]
        finally:
            store.close()
        assert n >= 1


class TestLikeEscaping:
    """``_`` and ``%`` in conventions must not act as wildcards."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("audit/testrisk.py", False),
            ("my_test_utils/x.py", False),
            ("src/latest_result.py", False),
            ("tests/test_x.py", True),
            ("a/test_b.py", True),
            ("test_a.py", True),
            ("a/b_test.py", True),
            ("web/a.spec.ts", True),
        ],
    )
    def test_is_test_path(self, tmp_path: Path, path: str, expected: bool) -> None:
        from debtector.graph_store import GraphStore

        store = GraphStore(tmp_path / "x.db")
        try:
            assert store.is_test_path(path) is expected
        finally:
            store.close()

    def test_test_path_prefix_with_wildcards_is_literal(self, tmp_path: Path) -> None:
        from debtector.graph_store import GraphStore

        store = GraphStore(tmp_path / "x.db")
        store.test_prefixes = ["my_checks%/"]
        try:
            assert store.is_test_path("my_checks%/a.py")
            assert not store.is_test_path("my_checksX/a.py")
        finally:
            store.close()
