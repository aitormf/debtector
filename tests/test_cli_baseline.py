"""Tests for `debtector baseline save` and `debtector baseline status`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from debtector.cli.baseline import cmd_baseline
from debtector.cli.common import _get_store
from debtector.logging import configure_logging
from debtector.metrics import METRICS_VERSION
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    configure_logging(project=str(tmp_path))


def _args(project: str, subcommand: str, **kwargs) -> argparse.Namespace:
    defaults = {"project": project, "json": False, "baseline_cmd": subcommand}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _file(path: str) -> NodeInfo:
    return NodeInfo(
        kind=NodeKind.FILE,
        name=path.split("/")[-1],
        qualified_name=path,
        file_path=path,
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


def _seed(project: str, files: dict[str, list[EdgeInfo]]) -> None:
    store = _get_store(project)
    for path, edges in files.items():
        store.store_file(path, [_file(path)], edges)
    store.close()


# ──────────────────────────────────────────────
# baseline save
# ──────────────────────────────────────────────


class TestBaselineSave:
    """debtector baseline save writes .debtector/baseline.json."""

    def test_creates_baseline_file(self, tmp_path: Path) -> None:
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        assert (tmp_path / ".debtector" / "baseline.json").exists()

    def test_baseline_contains_required_keys(self, tmp_path: Path) -> None:
        _seed(str(tmp_path), {"src/a.py": [_import("src/a.py", "src/b.py")]})
        cmd_baseline(_args(str(tmp_path), "save"))
        data = json.loads((tmp_path / ".debtector" / "baseline.json").read_text())
        assert "modules" in data
        assert "cycles" in data
        assert "god_modules" in data
        assert "saved_at" in data

    def test_baseline_modules_have_metrics(self, tmp_path: Path) -> None:
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [],
            },
        )
        cmd_baseline(_args(str(tmp_path), "save"))
        data = json.loads((tmp_path / ".debtector" / "baseline.json").read_text())
        mod = next(m for m in data["modules"] if m["file_path"] == "src/a.py")
        assert mod["fan_out"] > 0
        assert "instability" in mod

    def test_save_prints_confirmation(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        out = capsys.readouterr().out
        assert "baseline" in out.lower()

    def test_save_json_output(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args(str(tmp_path), "save", json=True))
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "saved"
        assert "path" in data

    def test_overwrites_existing_baseline(self, tmp_path: Path) -> None:
        """Running save twice updates the baseline."""
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        first = json.loads((tmp_path / ".debtector" / "baseline.json").read_text())

        # Add a new file
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        second = json.loads((tmp_path / ".debtector" / "baseline.json").read_text())

        assert len(second["modules"]) >= len(first["modules"])


# ──────────────────────────────────────────────
# baseline status
# ──────────────────────────────────────────────


class TestBaselineStatus:
    """debtector baseline status compares current metrics to baseline."""

    def test_no_baseline_prints_message(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args(str(tmp_path), "status"))
        out = capsys.readouterr().out
        assert "baseline" in out.lower()

    def test_no_changes_shows_ok(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": [_import("src/a.py", "src/b.py")]})
        cmd_baseline(_args(str(tmp_path), "save"))
        capsys.readouterr()  # clear save output

        cmd_baseline(_args(str(tmp_path), "status"))
        out = capsys.readouterr().out
        assert "no changes" in out.lower()

    def test_new_cycle_detected_as_regression(self, tmp_path: Path, capsys) -> None:
        """A cycle introduced after baseline is reported and exits 1."""
        _seed(str(tmp_path), {"src/a.py": [], "src/b.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        capsys.readouterr()

        # Introduce cycle
        _seed(
            str(tmp_path),
            {
                "src/a.py": [_import("src/a.py", "src/b.py")],
                "src/b.py": [_import("src/b.py", "src/a.py")],
            },
        )
        with pytest.raises(SystemExit) as exc:
            cmd_baseline(_args(str(tmp_path), "status"))
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "cycle" in out.lower()

    def test_status_json_output(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        capsys.readouterr()

        cmd_baseline(_args(str(tmp_path), "status", json=True))
        data = json.loads(capsys.readouterr().out)
        assert "regressions" in data
        assert "new_cycles" in data
        assert "new_god_modules" in data


class TestBaselineInstabilityTolerance:
    """The 0.05 tolerance is exact despite floating-point rounding."""

    def _seed_x_with_instability_0_4(self, project: str) -> None:
        # x.py: Ca=3 (i1, i2, i3 import it), Ce=2 (it imports o1, o2) → I = 2/5 = 0.4
        _seed(
            project,
            {
                "x.py": [_import("x.py", "o1.py"), _import("x.py", "o2.py")],
                "o1.py": [],
                "o2.py": [],
                "i1.py": [_import("i1.py", "x.py")],
                "i2.py": [_import("i2.py", "x.py")],
                "i3.py": [_import("i3.py", "x.py")],
            },
        )

    def _write_baseline(self, project: Path, instability: float) -> None:
        path = project / ".debtector" / "baseline.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        module = {"file_path": "x.py", "fan_in": 3, "fan_out": 2, "instability": instability}
        data = {"modules": [module], "cycles": [], "god_modules": []}
        data["metrics_version"] = METRICS_VERSION
        path.write_text(json.dumps(data))

    def test_delta_exactly_at_tolerance_is_not_a_regression(self, tmp_path: Path, capsys) -> None:
        """0.35 → 0.40: 0.35 + 0.05 is 0.39999999999999997 in floating point."""
        self._seed_x_with_instability_0_4(str(tmp_path))
        self._write_baseline(tmp_path, 0.35)
        cmd_baseline(_args(str(tmp_path), "status", json=True))
        assert json.loads(capsys.readouterr().out)["regressions"] == []

    def test_delta_above_tolerance_is_a_regression(self, tmp_path: Path, capsys) -> None:
        self._seed_x_with_instability_0_4(str(tmp_path))
        self._write_baseline(tmp_path, 0.3499)
        cmd_baseline(_args(str(tmp_path), "status", json=True))
        regressions = json.loads(capsys.readouterr().out)["regressions"]
        assert [r["file_path"] for r in regressions] == ["x.py"]


class TestBaselineMetricsVersion:
    """R1 (D-0014): the baseline records the coupling-metric version."""

    def _write_baseline(self, project: Path, **extra) -> None:
        path = project / ".debtector" / "baseline.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        module = {"file_path": "x.py", "fan_in": 0, "fan_out": 0, "instability": 0.0}
        data = {"modules": [module], "cycles": [], "god_modules": [], "sdp_violations": []}
        path.write_text(json.dumps({**data, **extra}))

    def _seed_cycle(self, project: Path) -> None:
        _seed(
            str(project),
            {
                "a.py": [_import("a.py", "b.py")],
                "b.py": [_import("b.py", "a.py")],
                "x.py": [],
            },
        )

    def test_E1_save_writes_metrics_version(self, tmp_path: Path) -> None:
        from debtector.metrics import METRICS_VERSION

        _seed(str(tmp_path), {"src/a.py": []})
        cmd_baseline(_args(str(tmp_path), "save"))
        data = json.loads((tmp_path / ".debtector" / "baseline.json").read_text())
        assert data["metrics_version"] == METRICS_VERSION

    def test_E2_baseline_without_version_is_compared_as_v1(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.setattr("debtector.metrics.METRICS_VERSION", 1)
        # x.py has Ca=3 / Ce=2 → I=0.4; the baseline (no version field) says 0.0
        _seed(
            str(tmp_path),
            {
                "x.py": [_import("x.py", "o1.py"), _import("x.py", "o2.py")],
                "o1.py": [],
                "o2.py": [],
                "i1.py": [_import("i1.py", "x.py")],
                "i2.py": [_import("i2.py", "x.py")],
                "i3.py": [_import("i3.py", "x.py")],
            },
        )
        self._write_baseline(tmp_path)
        cmd_baseline(_args(str(tmp_path), "status", json=True))
        data = json.loads(capsys.readouterr().out)
        assert [r["file_path"] for r in data["regressions"]] == ["x.py"]
        assert "metrics_version_mismatch" not in data

    def test_E3_other_version_warns_and_skips_ca_ce_comparisons(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.setattr("debtector.metrics.METRICS_VERSION", 2)
        _seed(str(tmp_path), {"x.py": [_import("x.py", "o.py")], "o.py": []})
        self._write_baseline(tmp_path, metrics_version=1)

        cmd_baseline(_args(str(tmp_path), "status"))
        out = capsys.readouterr().out
        assert "baseline saved with coupling metrics v1, current is v2" in out
        assert "debtector baseline save" in out
        assert "Instability regressions" not in out

        cmd_baseline(_args(str(tmp_path), "status", json=True))
        data = json.loads(capsys.readouterr().out)
        assert data["metrics_version_mismatch"] == {"baseline": 1, "current": 2}
        assert data["regressions"] == []
        assert data["new_god_modules"] == []
        assert data["new_sdp_violations"] == []

    def test_E4_other_version_still_compares_cycles(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.setattr("debtector.metrics.METRICS_VERSION", 2)
        (tmp_path / "debtector.toml").write_text(
            '[metrics.severity]\ncycles = "error"\n', encoding="utf-8"
        )
        self._seed_cycle(tmp_path)
        self._write_baseline(tmp_path, metrics_version=1)
        with pytest.raises(SystemExit) as exc:
            cmd_baseline(_args(str(tmp_path), "status"))
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "current is v2" in out
        assert "cycle" in out.lower()
