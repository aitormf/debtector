"""Tests for git_history module — behavioral coupling via git history."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from debtector.git_history import (
    compute_bus_factor,
    compute_hotspots,
    compute_temporal_coupling,
    parse_churn,
)
from debtector.graph_store import GraphStore
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _file(path: str) -> NodeInfo:
    return NodeInfo(
        kind=NodeKind.FILE,
        name=path.split("/")[-1],
        qualified_name=path,
        file_path=path,
        line_start=1,
        line_end=100,
        language="python",
    )


def _import(source: str, target: str) -> EdgeInfo:
    return EdgeInfo(
        kind=EdgeKind.IMPORTS_FROM,
        source=source,
        target=target,
        file_path=source,
        line=1,
    )


def _mock_run(stdout: str) -> MagicMock:
    """Return a mock for subprocess.run that yields the given stdout."""
    m = MagicMock()
    m.stdout = stdout
    return m


# ──────────────────────────────────────────────
# Fixtures — raw git output
# ──────────────────────────────────────────────

# SHA-1 hashes (40 hex chars) used as realistic fixtures
_HASH_A = "a" * 40
_HASH_B = "b" * 40
_HASH_C = "c" * 40

# Two commits touching three files:
#   HASH_A: auth.py (+3/-1), models.py (+10/-5)
#   HASH_B: auth.py (+1/-0), utils.py (+2/-2)
NUMSTAT_OUTPUT = (
    f"{_HASH_A}\n"
    "\n"
    "3\t1\tsrc/auth.py\n"
    "10\t5\tsrc/models.py\n"
    "\n"
    f"{_HASH_B}\n"
    "\n"
    "1\t0\tsrc/auth.py\n"
    "2\t2\tsrc/utils.py\n"
    "\n"
)

# Three commits covering all pairs:
#   HASH_A: auth.py, models.py
#   HASH_B: auth.py, utils.py
#   HASH_C: models.py, utils.py
NAME_ONLY_OUTPUT = (
    f"{_HASH_A}\n"
    "\n"
    "src/auth.py\n"
    "src/models.py\n"
    "\n"
    f"{_HASH_B}\n"
    "\n"
    "src/auth.py\n"
    "src/utils.py\n"
    "\n"
    f"{_HASH_C}\n"
    "\n"
    "src/models.py\n"
    "src/utils.py\n"
)

# 5 lines: Alice×3, Bob×2  →  top=Alice 60%, bus_factor=2
BLAME_OUTPUT = (
    "aaaa0001 1 1 3\n"
    "author Alice\n"
    "author-mail <alice@example.com>\n"
    "author-time 1700000000\n"
    "author-tz +0000\n"
    "committer Alice\n"
    "committer-mail <alice@example.com>\n"
    "committer-time 1700000000\n"
    "committer-tz +0000\n"
    "summary add auth\n"
    "filename src/auth.py\n"
    "\tdef login():\n"
    "aaaa0001 2 2\n"
    "author Alice\n"
    "author-mail <alice@example.com>\n"
    "author-time 1700000000\n"
    "author-tz +0000\n"
    "committer Alice\n"
    "committer-mail <alice@example.com>\n"
    "committer-time 1700000000\n"
    "committer-tz +0000\n"
    "summary add auth\n"
    "filename src/auth.py\n"
    "\t    pass\n"
    "aaaa0001 3 3\n"
    "author Alice\n"
    "author-mail <alice@example.com>\n"
    "author-time 1700000000\n"
    "author-tz +0000\n"
    "committer Alice\n"
    "committer-mail <alice@example.com>\n"
    "committer-time 1700000000\n"
    "committer-tz +0000\n"
    "summary add auth\n"
    "filename src/auth.py\n"
    "\t    return True\n"
    "bbbb0002 4 4 2\n"
    "author Bob\n"
    "author-mail <bob@example.com>\n"
    "author-time 1700000001\n"
    "author-tz +0000\n"
    "committer Bob\n"
    "committer-mail <bob@example.com>\n"
    "committer-time 1700000001\n"
    "committer-tz +0000\n"
    "summary fix auth\n"
    "filename src/auth.py\n"
    "\t    # fix\n"
    "bbbb0002 5 5\n"
    "author Bob\n"
    "author-mail <bob@example.com>\n"
    "author-time 1700000001\n"
    "author-tz +0000\n"
    "committer Bob\n"
    "committer-mail <bob@example.com>\n"
    "committer-time 1700000001\n"
    "committer-tz +0000\n"
    "summary fix auth\n"
    "filename src/auth.py\n"
    "\t    # end\n"
)


# ──────────────────────────────────────────────
# parse_churn
# ──────────────────────────────────────────────


class TestParseChurn:
    """Unit tests for parse_churn()."""

    def test_returns_churn_per_file(self, tmp_path: Path) -> None:
        with patch("subprocess.run", return_value=_mock_run(NUMSTAT_OUTPUT)):
            results = parse_churn(tmp_path)

        by_path = {m.file_path: m for m in results}
        assert set(by_path) == {"src/auth.py", "src/models.py", "src/utils.py"}

    def test_commit_count_deduped(self, tmp_path: Path) -> None:
        """auth.py appears in two distinct commits → commits=2."""
        with patch("subprocess.run", return_value=_mock_run(NUMSTAT_OUTPUT)):
            results = parse_churn(tmp_path)

        auth = next(m for m in results if m.file_path == "src/auth.py")
        assert auth.commits == 2

    def test_lines_accumulated(self, tmp_path: Path) -> None:
        """Lines are summed across commits."""
        with patch("subprocess.run", return_value=_mock_run(NUMSTAT_OUTPUT)):
            results = parse_churn(tmp_path)

        auth = next(m for m in results if m.file_path == "src/auth.py")
        assert auth.lines_added == 4  # 3 + 1
        assert auth.lines_deleted == 1  # 1 + 0

    def test_sorted_by_commits_desc(self, tmp_path: Path) -> None:
        with patch("subprocess.run", return_value=_mock_run(NUMSTAT_OUTPUT)):
            results = parse_churn(tmp_path)

        assert results[0].file_path == "src/auth.py"  # 2 commits
        assert results[0].commits >= results[-1].commits

    def test_empty_history_returns_empty(self, tmp_path: Path) -> None:
        with patch("subprocess.run", return_value=_mock_run("")):
            assert parse_churn(tmp_path) == []

    def test_since_flag_passed_to_git(self, tmp_path: Path) -> None:
        with patch("subprocess.run", return_value=_mock_run("")) as mock_run:
            parse_churn(tmp_path, since="6 months ago")

        cmd = mock_run.call_args[0][0]
        assert any("--since=6 months ago" in arg for arg in cmd)

    def test_git_not_found_raises_runtime_error(self, tmp_path: Path) -> None:

        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="git"):
                parse_churn(tmp_path)

    def test_git_error_raises_runtime_error(self, tmp_path: Path) -> None:
        import subprocess as sp

        err = sp.CalledProcessError(128, "git", stderr="not a git repository")
        with patch("subprocess.run", side_effect=err):
            with pytest.raises(RuntimeError):
                parse_churn(tmp_path)

    def test_binary_files_skipped(self, tmp_path: Path) -> None:
        """Binary files have '-' in added/deleted columns; should be handled."""
        output = f"{_HASH_A}\n\n-\t-\tsrc/image.png\n1\t0\tsrc/app.py\n\n"
        with patch("subprocess.run", return_value=_mock_run(output)):
            results = parse_churn(tmp_path)

        paths = {m.file_path for m in results}
        assert "src/image.png" in paths
        png = next(m for m in results if m.file_path == "src/image.png")
        assert png.lines_added == 0
        assert png.lines_deleted == 0


# ──────────────────────────────────────────────
# compute_hotspots
# ──────────────────────────────────────────────


class TestComputeHotspots:
    """Unit tests for compute_hotspots()."""

    def test_hotspot_score_is_churn_times_coupling(
        self, tmp_db: GraphStore, tmp_path: Path
    ) -> None:
        """score = churn × (fan_in + fan_out)."""
        # auth.py imports models.py → models has fan_in=1
        auth_edge = _import("src/auth.py", "src/models.py")
        tmp_db.store_file("src/auth.py", [_file("src/auth.py")], [auth_edge])
        tmp_db.store_file("src/models.py", [_file("src/models.py")], [])

        # auth.py: 2 commits; models.py: 1 commit
        with patch("subprocess.run", return_value=_mock_run(NUMSTAT_OUTPUT)):
            results = compute_hotspots(tmp_db, tmp_path)

        auth = next((h for h in results if h.file_path == "src/auth.py"), None)
        assert auth is not None
        # auth fan_out=1 (imports models), fan_in=0 → coupling=1; churn=2 → score=2
        assert auth.churn == 2
        assert auth.coupling == pytest.approx(1.0)
        assert auth.hotspot_score == pytest.approx(2.0)

    def test_sorted_by_score_desc(self, tmp_db: GraphStore, tmp_path: Path) -> None:
        auth_edge = _import("src/auth.py", "src/models.py")
        tmp_db.store_file("src/auth.py", [_file("src/auth.py")], [auth_edge])
        tmp_db.store_file("src/models.py", [_file("src/models.py")], [])

        with patch("subprocess.run", return_value=_mock_run(NUMSTAT_OUTPUT)):
            results = compute_hotspots(tmp_db, tmp_path)

        scores = [h.hotspot_score for h in results]
        assert scores == sorted(scores, reverse=True)

    def test_limit_respected(self, tmp_db: GraphStore, tmp_path: Path) -> None:
        tmp_db.store_file("src/auth.py", [_file("src/auth.py")], [])
        tmp_db.store_file("src/models.py", [_file("src/models.py")], [])

        with patch("subprocess.run", return_value=_mock_run(NUMSTAT_OUTPUT)):
            results = compute_hotspots(tmp_db, tmp_path, limit=1)

        assert len(results) == 1

    def test_empty_store_returns_empty(self, tmp_db: GraphStore, tmp_path: Path) -> None:
        with patch("subprocess.run", return_value=_mock_run(NUMSTAT_OUTPUT)):
            results = compute_hotspots(tmp_db, tmp_path)

        assert results == []

    def test_empty_history_returns_empty(self, tmp_db: GraphStore, tmp_path: Path) -> None:
        tmp_db.store_file("src/auth.py", [_file("src/auth.py")], [])

        with patch("subprocess.run", return_value=_mock_run("")):
            results = compute_hotspots(tmp_db, tmp_path)

        assert results == []


# ──────────────────────────────────────────────
# compute_temporal_coupling
# ──────────────────────────────────────────────


class TestComputeTemporalCoupling:
    """Unit tests for compute_temporal_coupling()."""

    def test_finds_co_changing_pairs(self, tmp_path: Path) -> None:
        with patch("subprocess.run", return_value=_mock_run(NAME_ONLY_OUTPUT)):
            results = compute_temporal_coupling(tmp_path, min_shared=1, min_ratio=0.0)

        pairs = {(t.file_a, t.file_b) for t in results}
        assert ("src/auth.py", "src/models.py") in pairs
        assert ("src/auth.py", "src/utils.py") in pairs
        assert ("src/models.py", "src/utils.py") in pairs

    def test_coupling_ratio_calculation(self, tmp_path: Path) -> None:
        """Each pair shares 1 out of 2 commits → ratio = 0.5."""
        with patch("subprocess.run", return_value=_mock_run(NAME_ONLY_OUTPUT)):
            results = compute_temporal_coupling(tmp_path, min_shared=1, min_ratio=0.0)

        for t in results:
            assert t.coupling_ratio == pytest.approx(0.5)

    def test_min_shared_filter(self, tmp_path: Path) -> None:
        """min_shared=2 filters out all pairs (each has only 1 shared commit)."""
        with patch("subprocess.run", return_value=_mock_run(NAME_ONLY_OUTPUT)):
            results = compute_temporal_coupling(tmp_path, min_shared=2, min_ratio=0.0)

        assert results == []

    def test_min_ratio_filter(self, tmp_path: Path) -> None:
        """min_ratio=0.8 filters out all pairs (all have ratio=0.5)."""
        with patch("subprocess.run", return_value=_mock_run(NAME_ONLY_OUTPUT)):
            results = compute_temporal_coupling(tmp_path, min_shared=1, min_ratio=0.8)

        assert results == []

    def test_pairs_are_ordered_file_a_lt_file_b(self, tmp_path: Path) -> None:
        """File pair order is canonical: file_a < file_b alphabetically."""
        with patch("subprocess.run", return_value=_mock_run(NAME_ONLY_OUTPUT)):
            results = compute_temporal_coupling(tmp_path, min_shared=1, min_ratio=0.0)

        for t in results:
            assert t.file_a <= t.file_b

    def test_sorted_by_shared_commits_desc(self, tmp_path: Path) -> None:
        with patch("subprocess.run", return_value=_mock_run(NAME_ONLY_OUTPUT)):
            results = compute_temporal_coupling(tmp_path, min_shared=1, min_ratio=0.0)

        shared = [t.shared_commits for t in results]
        assert shared == sorted(shared, reverse=True)

    def test_empty_history_returns_empty(self, tmp_path: Path) -> None:
        with patch("subprocess.run", return_value=_mock_run("")):
            results = compute_temporal_coupling(tmp_path, min_shared=1, min_ratio=0.0)

        assert results == []

    def test_since_flag_passed_to_git(self, tmp_path: Path) -> None:
        with patch("subprocess.run", return_value=_mock_run("")) as mock_run:
            compute_temporal_coupling(tmp_path, since="1 year ago")

        cmd = mock_run.call_args[0][0]
        assert any("--since=1 year ago" in arg for arg in cmd)


# ──────────────────────────────────────────────
# compute_bus_factor
# ──────────────────────────────────────────────


class TestComputeBusFactor:
    """Unit tests for compute_bus_factor()."""

    def test_top_author_identified(self, tmp_db: GraphStore, tmp_path: Path) -> None:
        """Alice has 3/5 lines → she is top author."""
        tmp_db.store_file("src/auth.py", [_file("src/auth.py")], [])

        with patch("subprocess.run", return_value=_mock_run(BLAME_OUTPUT)):
            results = compute_bus_factor(tmp_db, tmp_path)

        assert len(results) == 1
        r = results[0]
        assert r.file_path == "src/auth.py"
        assert r.top_author == "Alice"
        assert r.top_author_pct == pytest.approx(60.0, abs=0.1)

    def test_bus_factor_two_authors(self, tmp_db: GraphStore, tmp_path: Path) -> None:
        """Alice 60%, Bob 40%: need both to reach 80% → bus_factor=2."""
        tmp_db.store_file("src/auth.py", [_file("src/auth.py")], [])

        with patch("subprocess.run", return_value=_mock_run(BLAME_OUTPUT)):
            results = compute_bus_factor(tmp_db, tmp_path)

        assert results[0].bus_factor == 2

    def test_single_author_bus_factor_one(self, tmp_db: GraphStore, tmp_path: Path) -> None:
        """One author owns 100% → bus_factor=1."""
        blame = (
            "aaaa0001 1 1 2\n"
            "author Alice\nauthor-mail <a@x.com>\nauthor-time 1\nauthor-tz +0000\n"
            "committer Alice\ncommitter-mail <a@x.com>\ncommitter-time 1\ncommitter-tz +0000\n"
            "summary init\nfilename src/solo.py\n\tpass\n"
            "aaaa0001 2 2\n"
            "author Alice\nauthor-mail <a@x.com>\nauthor-time 1\nauthor-tz +0000\n"
            "committer Alice\ncommitter-mail <a@x.com>\ncommitter-time 1\ncommitter-tz +0000\n"
            "summary init\nfilename src/solo.py\n\treturn\n"
        )
        tmp_db.store_file("src/solo.py", [_file("src/solo.py")], [])

        with patch("subprocess.run", return_value=_mock_run(blame)):
            results = compute_bus_factor(tmp_db, tmp_path)

        assert results[0].bus_factor == 1
        assert results[0].top_author_pct == pytest.approx(100.0)

    def test_only_indexed_files_processed(self, tmp_db: GraphStore, tmp_path: Path) -> None:
        """Only files in the GraphStore are analysed."""
        tmp_db.store_file("src/auth.py", [_file("src/auth.py")], [])

        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            return _mock_run(BLAME_OUTPUT)

        with patch("subprocess.run", side_effect=fake_run):
            compute_bus_factor(tmp_db, tmp_path)

        assert call_count == 1  # only one file in store

    def test_empty_store_returns_empty(self, tmp_db: GraphStore, tmp_path: Path) -> None:
        with patch("subprocess.run", return_value=_mock_run(BLAME_OUTPUT)):
            results = compute_bus_factor(tmp_db, tmp_path)

        assert results == []

    def test_blame_error_skips_file(self, tmp_db: GraphStore, tmp_path: Path) -> None:
        """If git blame fails for a file, it is skipped gracefully."""
        import subprocess as sp

        tmp_db.store_file("src/auth.py", [_file("src/auth.py")], [])
        tmp_db.store_file("src/models.py", [_file("src/models.py")], [])

        def fake_run(cmd, **kwargs):
            if "src/auth.py" in cmd:
                raise sp.CalledProcessError(128, "git blame", stderr="error")
            return _mock_run(BLAME_OUTPUT)

        with patch("subprocess.run", side_effect=fake_run):
            results = compute_bus_factor(tmp_db, tmp_path)

        # auth.py skipped, models.py processed
        paths = {r.file_path for r in results}
        assert "src/auth.py" not in paths
        assert "src/models.py" in paths
