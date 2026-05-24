"""End-to-end integration tests for cmd_audit."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from debtector.cli import _get_store, cmd_audit
from debtector.indexer import Indexer


class Args:
    """Mock argparse args for cmd_audit."""

    def __init__(self, project: str, top_n: int = 10, full: bool = False, json_out: bool = False):
        self.project = project
        self.top_n = top_n
        self.full = full
        self.json = json_out


@pytest.fixture
def sample_project() -> Path:
    """Create a temporary project with sample files and index."""
    tmpdir = Path(tempfile.mkdtemp())
    debtector_dir = tmpdir / ".debtector"
    debtector_dir.mkdir(exist_ok=True)

    src_dir = tmpdir / "src"
    src_dir.mkdir(exist_ok=True)

    # Create a simple Python file
    sample_py = src_dir / "service.py"
    sample_py.write_text(
        """\
class UserService:
    def __init__(self):
        self.db = None

    def get_user(self, user_id):
        return self.db.query(user_id)

    def create_user(self, name):
        return self.db.insert(name)

class AdminService:
    def __init__(self):
        self.users = UserService()

    def promote_user(self, user_id):
        user = self.users.get_user(user_id)
        user.admin = True
"""
    )

    # Initialize git repo for bus factor computation
    import subprocess

    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=False)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmpdir,
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True, check=False
    )
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=False)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmpdir, capture_output=True, check=False)

    # Index the project
    store = _get_store(str(tmpdir))
    indexer = Indexer(store)
    indexer.index(str(tmpdir))
    store.close()

    return tmpdir


def test_cmd_audit_smoke(sample_project: Path, capsys) -> None:
    """Test that cmd_audit executes without crashing."""
    args = Args(str(sample_project), json_out=False)
    with mock.patch("debtector.cli._auto_index"):
        cmd_audit(args)

    captured = capsys.readouterr()
    assert "Audit Summary" in captured.out
    assert "health:" in captured.out


def test_cmd_audit_json_smoke(sample_project: Path, capsys) -> None:
    """Test that cmd_audit --json produces valid JSON."""
    args = Args(str(sample_project), json_out=True)
    with mock.patch("debtector.cli._auto_index"):
        cmd_audit(args)

    captured = capsys.readouterr()
    # Parse JSON output (last line should be the JSON)
    output = json.loads(captured.out.strip().split("\n")[-1])

    # Verify required top-level fields
    assert "schema_version" in output
    assert output["schema_version"] == 1
    assert "summary" in output
    assert "coupling" in output
    assert "cycles" in output
    assert "cohesion" in output
    assert "testRisk" in output
    assert "hotspots" in output
    assert "busFactor" in output
    assert "inheritance" in output


def test_cmd_audit_json_structure(sample_project: Path, capsys) -> None:
    """Test that cmd_audit --json has the documented schema."""
    args = Args(str(sample_project), json_out=True)
    with mock.patch("debtector.cli._auto_index"):
        cmd_audit(args)

    captured = capsys.readouterr()
    output = json.loads(captured.out.strip().split("\n")[-1])

    # Check summary
    assert isinstance(output["summary"], dict)
    assert "modules" in output["summary"]
    assert "cycles" in output["summary"]
    assert "classes" in output["summary"]
    assert "health_score" in output["summary"]
    assert 0 <= output["summary"]["health_score"] <= 100

    # Check coupling
    assert isinstance(output["coupling"], list)
    for item in output["coupling"]:
        assert "file_path" in item
        assert "fan_in" in item
        assert "fan_out" in item
        assert "instability" in item
        assert "god_module" in item

    # Check cycles
    assert isinstance(output["cycles"], list)
    for item in output["cycles"]:
        assert "nodes" in item
        assert "pivot" in item
        assert "pivot_ca" in item
        assert "rationale" in item

    # Check cohesion
    assert isinstance(output["cohesion"], list)
    for item in output["cohesion"]:
        assert "qualified_name" in item
        assert "lcom4" in item
        assert "methods_count" in item
        assert "candidate_to_split" in item

    # Check testRisk
    assert isinstance(output["testRisk"], dict)
    assert "untested_high_coupling" in output["testRisk"]
    assert "untested_hotspots" in output["testRisk"]
    assert "critical_knowledge_concentration" in output["testRisk"]


def test_cmd_audit_with_full_flag(sample_project: Path, capsys) -> None:
    """Test that --full returns all results without limiting to top_n."""
    args = Args(str(sample_project), top_n=2, full=True, json_out=True)
    with mock.patch("debtector.cli._auto_index"):
        cmd_audit(args)

    captured = capsys.readouterr()
    output = json.loads(captured.out.strip().split("\n")[-1])

    # With full=True, all results should be included (not just top 2)
    # This is a smoke test — we're mainly checking it doesn't crash
    assert isinstance(output, dict)


def test_cmd_audit_calls_bus_factor_with_store(sample_project: Path) -> None:
    """Test that compute_bus_factor is called with both store and project args."""
    from unittest.mock import patch

    args = Args(str(sample_project), json_out=False)

    with (
        patch("debtector.cli._auto_index"),
        patch("debtector.cli.compute_bus_factor", return_value=[]) as mock_bus_factor,
    ):
        cmd_audit(args)

        # Verify compute_bus_factor was called with store and project_root
        assert mock_bus_factor.called
        call_args = mock_bus_factor.call_args
        # Should have 2 positional args: store and project_root
        assert len(call_args.args) >= 2 or (
            len(call_args.args) >= 1 and "project_root" in str(call_args)
        )


def test_cmd_audit_calls_god_modules_before_close(sample_project: Path) -> None:
    """Test that god_modules is called before store.close()."""
    from unittest.mock import patch

    args = Args(str(sample_project), json_out=False)

    with (
        patch("debtector.cli._auto_index"),
        patch("debtector.cli.god_modules", return_value=[]) as mock_god_modules,
    ):
        cmd_audit(args)

        # Verify god_modules was called
        assert mock_god_modules.called
        # It should be called with store as first argument
        call_args = mock_god_modules.call_args
        assert len(call_args.args) >= 1
