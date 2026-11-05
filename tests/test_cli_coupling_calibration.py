"""CLI behaviour of the coupling calibration: god-module min Ca and SDP violations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from debtector.cli import _get_store, cmd_baseline, cmd_coupling, cmd_report
from debtector.logging import configure_logging
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


@pytest.fixture(autouse=True)
def _redirect_logs(tmp_path: Path) -> None:
    configure_logging(project=str(tmp_path))


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
        kind=EdgeKind.IMPORTS_FROM, source=source, target=target, file_path=source, line=1
    )


def _seed(project: str, files: dict[str, list[str]]) -> None:
    store = _get_store(project)
    for path, targets in files.items():
        store.store_file(path, [_file(path)], [_import(path, t) for t in targets])
    store.close()


# a: I=0.25, b: I=0.667, a -> b violates SDP; x0..x2 are leaves with I=1.
_VIOLATING = {
    "src/x0.py": ["src/a.py"],
    "src/x1.py": ["src/a.py"],
    "src/x2.py": ["src/a.py"],
    "src/a.py": ["src/b.py"],
    "src/b.py": ["flask", "requests"],
}
_CLEAN = {**_VIOLATING, "src/a.py": []}


def _coupling_args(project: str, json: bool = False) -> argparse.Namespace:
    return argparse.Namespace(project=project, json=json, sort="fan_in", limit=None)


def _baseline_args(project: str, sub: str, json: bool = False) -> argparse.Namespace:
    return argparse.Namespace(project=project, json=json, baseline_cmd=sub)


class TestCouplingOutput:
    def test_json_flags_only_sdp_targets(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), _VIOLATING)
        cmd_coupling(_coupling_args(str(tmp_path), json=True))
        data = json.loads(capsys.readouterr().out)
        by_path = {m["file_path"]: m for m in data["modules"]}
        assert by_path["src/b.py"]["unstable"] is True
        assert by_path["src/x0.py"]["unstable"] is False  # leaf, I=1
        assert by_path["src/x0.py"]["instability"] == 1.0
        assert data["sdp_violations"] == [
            {
                "source": "src/a.py",
                "target": "src/b.py",
                "source_instability": 0.25,
                "target_instability": 0.667,
            }
        ]

    def test_human_marks_only_sdp_targets(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), _VIOLATING)
        cmd_coupling(_coupling_args(str(tmp_path)))
        lines = capsys.readouterr().out.splitlines()
        assert any("src/b.py" in ln and "inestable" in ln for ln in lines)
        assert not any("src/x0.py" in ln and "inestable" in ln for ln in lines)

    def test_min_ca_from_config_reaches_god_detection(self, tmp_path: Path, capsys) -> None:
        files: dict[str, list[str]] = {f"src/u{i}.py": ["src/hub.py"] for i in range(5)}
        files["src/hub.py"] = []
        files.update({f"src/q{i}.py": [] for i in range(10)})
        _seed(str(tmp_path), files)
        cmd_coupling(_coupling_args(str(tmp_path), json=True))
        assert json.loads(capsys.readouterr().out)["god_modules"] == []

        (tmp_path / "debtector.toml").write_text(
            "[metrics.thresholds]\ngod_module_min_ca = 3\n", encoding="utf-8"
        )
        cmd_coupling(_coupling_args(str(tmp_path), json=True))
        assert json.loads(capsys.readouterr().out)["god_modules"] == ["src/hub.py"]

    def test_report_json_flags_follow_sdp(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), _VIOLATING)
        args = argparse.Namespace(project=str(tmp_path), json=True, limit=None)
        cmd_report(args)
        data = json.loads(capsys.readouterr().out)
        flagged = {m["file_path"]: m["instability_flag"] for m in data["modules"]}
        assert flagged == {"src/b.py": True}


class TestBaselineSdp:
    def test_save_records_sdp_violations(self, tmp_path: Path) -> None:
        _seed(str(tmp_path), _VIOLATING)
        cmd_baseline(_baseline_args(str(tmp_path), "save"))
        saved = json.loads((tmp_path / ".debtector" / "baseline.json").read_text())
        assert saved["sdp_violations"] == [{"source": "src/a.py", "target": "src/b.py"}]

    def test_new_violation_after_baseline_is_worse(self, tmp_path: Path, capsys) -> None:
        (tmp_path / "debtector.toml").write_text(
            '[metrics.severity]\ninstability = "error"\n', encoding="utf-8"
        )
        _seed(str(tmp_path), _CLEAN)
        cmd_baseline(_baseline_args(str(tmp_path), "save"))
        _seed(str(tmp_path), {"src/a.py": ["src/b.py"]})
        capsys.readouterr()
        with pytest.raises(SystemExit) as exc:
            cmd_baseline(_baseline_args(str(tmp_path), "status", json=True))
        assert exc.value.code == 1
        out = json.loads(capsys.readouterr().out)
        assert out["new_sdp_violations"][0]["target"] == "src/b.py"

    def test_existing_violation_is_not_a_regression(self, tmp_path: Path, capsys) -> None:
        _seed(str(tmp_path), _VIOLATING)
        cmd_baseline(_baseline_args(str(tmp_path), "save"))
        capsys.readouterr()
        cmd_baseline(_baseline_args(str(tmp_path), "status"))
        assert "Sin cambios" in capsys.readouterr().out

    def test_old_format_baseline_gives_no_false_regression(self, tmp_path: Path, capsys) -> None:
        """A baseline saved before SDP existed has no ``sdp_violations``: no previous data."""
        (tmp_path / "debtector.toml").write_text(
            '[metrics.severity]\ninstability = "error"\n', encoding="utf-8"
        )
        _seed(str(tmp_path), _VIOLATING)
        cmd_baseline(_baseline_args(str(tmp_path), "save"))
        path = tmp_path / ".debtector" / "baseline.json"
        old = json.loads(path.read_text())
        del old["sdp_violations"]
        path.write_text(json.dumps(old), encoding="utf-8")
        capsys.readouterr()

        cmd_baseline(_baseline_args(str(tmp_path), "status"))  # must not exit 1 or crash
        assert "Sin cambios" in capsys.readouterr().out
