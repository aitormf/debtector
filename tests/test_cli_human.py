"""Tests for CLI human-readable (non-JSON) output and main() dispatch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

from debtector.cli.app import main
from debtector.cli.common import _get_store
from debtector.cli.graph import (
    cmd_callers,
    cmd_impact,
    cmd_imports,
    cmd_index,
    cmd_search,
    cmd_status,
    cmd_summary,
)

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _args(**kwargs) -> argparse.Namespace:
    """Build a simple Namespace for CLI functions.

    Args:
        **kwargs: Overrides for default values.

    Returns:
        An :class:`argparse.Namespace` with sensible defaults.
    """
    defaults = {"project": ".", "json": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _seed_store(project: str, src: Path) -> None:
    """Index *src* into the project store.

    Args:
        project: Project root path string.
        src: Directory to index.
    """
    from debtector.indexer import Indexer

    store = _get_store(project)
    Indexer(store).index(str(src))
    store.close()


@pytest.fixture()
def project(tmp_path: Path) -> tuple[str, Path]:
    """Return (project_str, src_dir) with a minimal Python file pre-indexed.

    Returns:
        Tuple of project root path string and source directory.
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "service.py").write_text(
        "import os\n\nclass MyService:\n    def run(self) -> None:\n        pass\n",
        encoding="utf-8",
    )
    _seed_store(str(tmp_path), src)
    return str(tmp_path), src


# ──────────────────────────────────────────────
# cmd_index — human-readable output
# ──────────────────────────────────────────────


class TestCmdIndexHuman:
    """cmd_index with json=False prints a human-readable summary."""

    def test_prints_indexing_message(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Prints 'Indexing' before scanning."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("def f(): pass\n", encoding="utf-8")
        cmd_index(_args(project=str(tmp_path), json=False, path=str(src)))
        out = capsys.readouterr().out
        assert "Indexing" in out

    def test_prints_stats_labels(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Prints scanned/indexed/skipped/errors/removed counters."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("def f(): pass\n", encoding="utf-8")
        cmd_index(_args(project=str(tmp_path), json=False, path=str(src)))
        out = capsys.readouterr().out
        assert "Indexed" in out
        assert "Unchanged" in out
        assert "Errors" in out
        assert "Deleted" in out


# ──────────────────────────────────────────────
# cmd_search — human-readable output
# ──────────────────────────────────────────────


class TestCmdSearchHuman:
    """cmd_search with json=False prints human-readable results."""

    def test_prints_query_header(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints the searched query string in the header."""
        proj, _ = project
        cmd_search(_args(project=proj, json=False, query="MyService", kind=None))
        out = capsys.readouterr().out
        assert "MyService" in out

    def test_prints_total(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints a Total line at the end."""
        proj, _ = project
        cmd_search(_args(project=proj, json=False, query="MyService", kind=None))
        out = capsys.readouterr().out
        assert "Total:" in out

    def test_prints_symbol_kind_and_name(
        self, project: tuple, capsys: pytest.CaptureFixture
    ) -> None:
        """Prints kind and qualified_name for each result."""
        proj, _ = project
        cmd_search(_args(project=proj, json=False, query="MyService", kind=None))
        out = capsys.readouterr().out
        assert "Class" in out

    def test_no_results_prints_zero_total(
        self, project: tuple, capsys: pytest.CaptureFixture
    ) -> None:
        """Prints 'Total: 0' when no matches are found."""
        proj, _ = project
        cmd_search(_args(project=proj, json=False, query="zzznomatch", kind=None))
        out = capsys.readouterr().out
        assert "Total: 0" in out


# ──────────────────────────────────────────────
# cmd_summary — human-readable output
# ──────────────────────────────────────────────


class TestCmdSummaryHuman:
    """cmd_summary with json=False prints file symbols and relations."""

    def test_prints_file_path(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints the file path and language in the header.

        The indexer stores paths relative to the indexed directory, so
        ``service.py`` (not ``src/service.py``) is the stored key.
        """
        proj, _ = project
        cmd_summary(_args(project=proj, json=False, file="service.py"))
        out = capsys.readouterr().out
        assert "service.py" in out

    def test_prints_symbols_section(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints 'Symbols:' heading when nodes exist."""
        proj, _ = project
        cmd_summary(_args(project=proj, json=False, file="service.py"))
        out = capsys.readouterr().out
        assert "Symbols" in out

    def test_not_found_human_exits_1(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Exits with code 1 when file is absent from index."""
        proj, _ = project
        with pytest.raises(SystemExit) as exc:
            cmd_summary(_args(project=proj, json=False, file="no/such.py"))
        assert exc.value.code == 1

    def test_not_found_human_prints_message(
        self, project: tuple, capsys: pytest.CaptureFixture
    ) -> None:
        """Prints a human-readable 'not found' message."""
        proj, _ = project
        with pytest.raises(SystemExit):
            cmd_summary(_args(project=proj, json=False, file="no/such.py"))
        out = capsys.readouterr().out
        assert "no/such.py" in out

    def test_not_found_json_exits_1(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Exits with code 1 when file is absent (json mode)."""
        import json

        proj, _ = project
        with pytest.raises(SystemExit) as exc:
            cmd_summary(_args(project=proj, json=True, file="no/such.py"))
        assert exc.value.code == 1
        out = json.loads(capsys.readouterr().out)
        assert "error" in out

    def test_json_success(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Returns JSON with path key when file is found."""
        import json

        proj, _ = project
        cmd_summary(_args(project=proj, json=True, file="service.py"))
        out = json.loads(capsys.readouterr().out)
        assert "path" in out


# ──────────────────────────────────────────────
# cmd_impact — human-readable output
# ──────────────────────────────────────────────


class TestCmdImpactHuman:
    """cmd_impact with json=False prints an impact analysis."""

    def test_prints_analysis_header(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints the 'Impact analysis' header."""
        proj, _ = project
        cmd_impact(_args(project=proj, json=False, files=["src/service.py"], depth=2))
        out = capsys.readouterr().out
        assert "impact" in out.lower()

    def test_prints_changed_nodes_count(
        self, project: tuple, capsys: pytest.CaptureFixture
    ) -> None:
        """Prints the number of changed nodes."""
        proj, _ = project
        cmd_impact(_args(project=proj, json=False, files=["src/service.py"], depth=2))
        out = capsys.readouterr().out
        assert "changed" in out.lower()

    def test_json_output(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """JSON mode emits changed_nodes and impacted_files keys."""
        import json

        proj, _ = project
        cmd_impact(_args(project=proj, json=True, files=["src/service.py"], depth=2))
        out = json.loads(capsys.readouterr().out)
        assert "changed_nodes" in out
        assert "impacted_files" in out


# ──────────────────────────────────────────────
# cmd_imports — human-readable output
# ──────────────────────────────────────────────


class TestCmdImportsHuman:
    """cmd_imports with json=False prints module import locations."""

    def test_prints_module_header(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints the module name in the output header."""
        proj, _ = project
        cmd_imports(_args(project=proj, json=False, module="os"))
        out = capsys.readouterr().out
        assert "os" in out

    def test_prints_total(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints a Total line."""
        proj, _ = project
        cmd_imports(_args(project=proj, json=False, module="os"))
        out = capsys.readouterr().out
        assert "Total:" in out

    def test_prints_file_path_when_found(
        self, project: tuple, capsys: pytest.CaptureFixture
    ) -> None:
        """Prints the file path when an import match is found."""
        proj, _ = project
        cmd_imports(_args(project=proj, json=False, module="os"))
        out = capsys.readouterr().out
        # service.py imports os
        assert "service.py" in out


# ──────────────────────────────────────────────
# cmd_status — human-readable output
# ──────────────────────────────────────────────


class TestCmdStatusHuman:
    """cmd_status with json=False prints index statistics."""

    def test_prints_estado_header(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints the 'Index status' header."""
        proj, _ = project
        cmd_status(_args(project=proj, json=False))
        out = capsys.readouterr().out
        assert "status" in out.lower()

    def test_prints_archivos_count(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints 'Files:' with a count."""
        proj, _ = project
        cmd_status(_args(project=proj, json=False))
        out = capsys.readouterr().out
        assert "Files:" in out

    def test_prints_nodos_per_kind(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints 'Nodes by kind:' breakdown."""
        proj, _ = project
        cmd_status(_args(project=proj, json=False))
        out = capsys.readouterr().out
        assert "kind" in out.lower()

    def test_prints_edges_per_kind(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints 'Aristas por tipo:' breakdown."""
        proj, _ = project
        cmd_status(_args(project=proj, json=False))
        out = capsys.readouterr().out
        assert "Edges" in out


# ──────────────────────────────────────────────
# cmd_callers — both output modes
# ──────────────────────────────────────────────


class TestCmdCallersHuman:
    """cmd_callers prints callers of a symbol."""

    def test_human_prints_quien_llama(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints 'Who calls …?' header."""
        proj, _ = project
        cmd_callers(_args(project=proj, json=False, qualified_name="src/service.py::MyService"))
        out = capsys.readouterr().out
        assert "calls" in out.lower()

    def test_human_prints_total(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints a Total line."""
        proj, _ = project
        cmd_callers(_args(project=proj, json=False, qualified_name="src/service.py::MyService"))
        out = capsys.readouterr().out
        assert "Total:" in out

    def test_json_returns_list(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """JSON mode emits a JSON array."""
        import json

        proj, _ = project
        cmd_callers(_args(project=proj, json=True, qualified_name="src/service.py::MyService"))
        out = json.loads(capsys.readouterr().out)
        assert isinstance(out, list)


class TestMainEntry:
    """main() parses sys.argv and dispatches to sub-commands."""

    def test_no_command_exits_0(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Exits with code 0 and prints help when no sub-command is given."""
        with pytest.raises(SystemExit) as exc:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(sys, "argv", ["debtector", "--project", str(tmp_path)])
                main()
        assert exc.value.code == 0

    def test_status_command_via_main(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """main() dispatches 'status' and produces output."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "argv", ["debtector", "--project", str(tmp_path), "--json", "status"])
            main()
        out = capsys.readouterr().out
        assert out.strip()  # some JSON output produced

    def test_index_command_via_main(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """main() dispatches 'index' and produces stats output."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("x = 1\n", encoding="utf-8")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                sys,
                "argv",
                ["debtector", "--project", str(tmp_path), "--json", "index", str(src)],
            )
            main()
        import json

        out = json.loads(capsys.readouterr().out)
        assert "scanned" in out

    def test_search_command_via_main(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """main() dispatches 'search' and returns a JSON list."""
        import json

        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("class Foo: pass\n", encoding="utf-8")
        _seed_store(str(tmp_path), src)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                sys,
                "argv",
                ["debtector", "--project", str(tmp_path), "--json", "search", "Foo"],
            )
            main()
        out = json.loads(capsys.readouterr().out)
        assert isinstance(out, list)

    def test_summary_command_via_main(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """main() dispatches 'summary' and returns JSON with path key.

        The file is indexed relative to the src/ directory, so the stored
        path key is ``app.py`` (not ``src/app.py``).
        """
        import json

        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("class Foo: pass\n", encoding="utf-8")
        _seed_store(str(tmp_path), src)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                sys,
                "argv",
                ["debtector", "--project", str(tmp_path), "--json", "summary", "app.py"],
            )
            main()
        out = json.loads(capsys.readouterr().out)
        assert "path" in out

    def test_impact_command_via_main(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """main() dispatches 'impact' and returns JSON with changed_nodes key."""
        import json

        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("class Foo: pass\n", encoding="utf-8")
        _seed_store(str(tmp_path), src)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                sys,
                "argv",
                [
                    "debtector",
                    "--project",
                    str(tmp_path),
                    "--json",
                    "impact",
                    "src/app.py",
                ],
            )
            main()
        out = json.loads(capsys.readouterr().out)
        assert "changed_nodes" in out

    def test_imports_command_via_main(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """main() dispatches 'imports' and returns a JSON list."""
        import json

        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("import os\n", encoding="utf-8")
        _seed_store(str(tmp_path), src)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                sys,
                "argv",
                ["debtector", "--project", str(tmp_path), "--json", "imports", "os"],
            )
            main()
        out = json.loads(capsys.readouterr().out)
        assert isinstance(out, list)

    def test_callers_command_via_main(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """main() dispatches 'callers' and returns a JSON list."""
        import json

        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("def helper(): pass\n", encoding="utf-8")
        _seed_store(str(tmp_path), src)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                sys,
                "argv",
                [
                    "debtector",
                    "--project",
                    str(tmp_path),
                    "--json",
                    "callers",
                    "src/app.py::helper",
                ],
            )
            main()
        out = json.loads(capsys.readouterr().out)
        assert isinstance(out, list)


class TestGlobalOptionsPosition:
    """--json and --project are accepted before and after the sub-command."""

    @staticmethod
    def _parse(
        monkeypatch: pytest.MonkeyPatch, command: str, argv: list[str]
    ) -> argparse.Namespace:
        """Run main() with ``argv`` and return the Namespace given to the handler."""
        captured: dict[str, argparse.Namespace] = {}
        monkeypatch.setattr(
            f"debtector.cli.app.cmd_{command}", lambda args: captured.setdefault("args", args)
        )
        monkeypatch.setattr("debtector.cli.app.configure_logging", lambda **kwargs: None)
        monkeypatch.setattr(sys, "argv", ["debtector", *argv])
        main()
        return captured["args"]

    @pytest.mark.parametrize(
        ("command", "sub"), [("status", ["status"]), ("baseline", ["baseline", "status"])]
    )
    def test_json_positions(
        self, monkeypatch: pytest.MonkeyPatch, command: str, sub: list[str]
    ) -> None:
        """--json is True before or after the sub-command and False when omitted."""
        before = self._parse(monkeypatch, command, ["--json", *sub])
        after = self._parse(monkeypatch, command, [*sub, "--json"])
        absent = self._parse(monkeypatch, command, sub)
        assert (before.json, after.json, absent.json) == (True, True, False)

    @pytest.mark.parametrize(
        ("command", "sub"), [("status", ["status"]), ("baseline", ["baseline", "status"])]
    )
    def test_project_positions(
        self, monkeypatch: pytest.MonkeyPatch, command: str, sub: list[str]
    ) -> None:
        """--project works before or after the sub-command; default is '.'."""
        before = self._parse(monkeypatch, command, ["--project", "/x", *sub])
        after = self._parse(monkeypatch, command, [*sub, "--project", "/x"])
        absent = self._parse(monkeypatch, command, sub)
        assert (before.project, after.project, absent.project) == ("/x", "/x", ".")

    def test_value_before_subcommand_not_overwritten(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A global option given first survives the sub-parser defaults."""
        args = self._parse(monkeypatch, "baseline", ["-p", "/x", "--json", "baseline", "save"])
        assert (args.project, args.json) == ("/x", True)
