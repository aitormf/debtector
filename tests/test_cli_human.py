"""Tests for CLI human-readable (non-JSON) output and main() dispatch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

from codeindex.cli import (
    _get_store,
    cmd_callers,
    cmd_impact,
    cmd_imports,
    cmd_index,
    cmd_install_hook,
    cmd_install_skill,
    cmd_search,
    cmd_status,
    cmd_summary,
    main,
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
    from codeindex.indexer import Indexer

    store = _get_store(project)
    Indexer(store).index(str(src))
    store.close()


def _fake_git_repo(tmp_path: Path) -> Path:
    """Create a minimal .git/hooks/ directory structure.

    Args:
        tmp_path: Temporary directory to use as repo root.

    Returns:
        Path to the ``.git/hooks/`` directory.
    """
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    return hooks


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
        """Prints 'Indexando' before scanning."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("def f(): pass\n", encoding="utf-8")
        cmd_index(_args(project=str(tmp_path), json=False, path=str(src)))
        out = capsys.readouterr().out
        assert "Indexando" in out

    def test_prints_stats_labels(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Prints scanned/indexed/skipped/errors/removed counters."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("def f(): pass\n", encoding="utf-8")
        cmd_index(_args(project=str(tmp_path), json=False, path=str(src)))
        out = capsys.readouterr().out
        assert "Indexados" in out
        assert "Sin cambios" in out
        assert "Errores" in out
        assert "Eliminados" in out


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
        """Prints 'Símbolos:' heading when nodes exist."""
        proj, _ = project
        cmd_summary(_args(project=proj, json=False, file="service.py"))
        out = capsys.readouterr().out
        assert "Símbolos" in out

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
        """Prints the 'Análisis de impacto' header."""
        proj, _ = project
        cmd_impact(_args(project=proj, json=False, files=["src/service.py"], depth=2))
        out = capsys.readouterr().out
        assert "impacto" in out.lower()

    def test_prints_changed_nodes_count(
        self, project: tuple, capsys: pytest.CaptureFixture
    ) -> None:
        """Prints the number of changed nodes."""
        proj, _ = project
        cmd_impact(_args(project=proj, json=False, files=["src/service.py"], depth=2))
        out = capsys.readouterr().out
        assert "cambiados" in out.lower()

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
        """Prints the 'Estado del índice' header."""
        proj, _ = project
        cmd_status(_args(project=proj, json=False))
        out = capsys.readouterr().out
        assert "Estado" in out

    def test_prints_archivos_count(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints 'Archivos:' with a count."""
        proj, _ = project
        cmd_status(_args(project=proj, json=False))
        out = capsys.readouterr().out
        assert "Archivos:" in out

    def test_prints_nodos_per_kind(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints 'Nodos por tipo:' breakdown."""
        proj, _ = project
        cmd_status(_args(project=proj, json=False))
        out = capsys.readouterr().out
        assert "tipo" in out.lower()

    def test_prints_edges_per_kind(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints 'Aristas por tipo:' breakdown."""
        proj, _ = project
        cmd_status(_args(project=proj, json=False))
        out = capsys.readouterr().out
        assert "Aristas" in out


# ──────────────────────────────────────────────
# cmd_callers — both output modes
# ──────────────────────────────────────────────


class TestCmdCallersHuman:
    """cmd_callers prints callers of a symbol."""

    def test_human_prints_quien_llama(self, project: tuple, capsys: pytest.CaptureFixture) -> None:
        """Prints '¿Quién llama a …?' header."""
        proj, _ = project
        cmd_callers(_args(project=proj, json=False, qualified_name="src/service.py::MyService"))
        out = capsys.readouterr().out
        assert "llama" in out.lower()

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


# ──────────────────────────────────────────────
# cmd_install_skill — human-readable output
# ──────────────────────────────────────────────


class TestCmdInstallSkillHuman:
    """cmd_install_skill with json=False prints installed file paths."""

    def test_human_prints_instalado(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Prints 'Instalado:' for each skill file."""
        cmd_install_skill(_args(project=str(tmp_path), json=False, global_install=False))
        out = capsys.readouterr().out
        assert "Instalado" in out or "instalados" in out.lower()

    def test_human_shows_dest_path(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Prints the destination directory."""
        cmd_install_skill(_args(project=str(tmp_path), json=False, global_install=False))
        out = capsys.readouterr().out
        assert ".claude" in out

    def test_global_install_uses_home(
        self, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """global_install=True installs under the home directory."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr("codeindex.cli.Path.home", lambda: fake_home)
        cmd_install_skill(_args(project=str(tmp_path), json=False, global_install=True))
        assert (fake_home / ".claude" / "skills").exists()

    def test_global_install_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """global_install=True with json=True returns correct dest."""
        import json

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr("codeindex.cli.Path.home", lambda: fake_home)
        cmd_install_skill(_args(project=str(tmp_path), json=True, global_install=True))
        out = json.loads(capsys.readouterr().out)
        assert ".claude" in out["dest"]

    def test_skills_not_found_human_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exits with code 1 when skills directory does not exist (human mode)."""
        # Patch skills_src to a non-existent path
        from pathlib import Path as RealPath
        from unittest.mock import patch

        fake_skills = tmp_path / "no_skills_here"
        with patch(
            "codeindex.cli.Path.__truediv__",
            side_effect=lambda self, other: (
                fake_skills
                if other == "skills" and str(self).endswith("codeindex")
                else RealPath.__truediv__(self, other)
            ),
        ):
            pass  # too complex; use simpler monkeypatch on the module attribute

        # Simpler: patch __file__ attribute of the cli module
        import codeindex.cli as cli_mod

        # Point cli.__file__ at a dir where 'skills' subdir does not exist
        monkeypatch.setattr(cli_mod, "__file__", str(tmp_path / "fake_cli.py"))
        with pytest.raises(SystemExit) as exc:
            cmd_install_skill(_args(project=str(tmp_path), json=False, global_install=False))
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "Error" in err

    def test_skills_not_found_json_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exits with code 1 when skills directory does not exist (json mode)."""
        import json

        import codeindex.cli as cli_mod

        monkeypatch.setattr(cli_mod, "__file__", str(tmp_path / "fake_cli.py"))
        with pytest.raises(SystemExit) as exc:
            cmd_install_skill(_args(project=str(tmp_path), json=True, global_install=False))
        assert exc.value.code == 1
        out = json.loads(capsys.readouterr().out)
        assert "error" in out


# ──────────────────────────────────────────────
# cmd_install_hook — human-readable error path
# ──────────────────────────────────────────────


class TestCmdInstallHookHuman:
    """cmd_install_hook human-readable messages."""

    def test_no_git_human_prints_to_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Prints 'Error:' to stderr when no .git dir is found."""
        with pytest.raises(SystemExit) as exc:
            cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=False))
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "Error" in err

    def test_human_created_message(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Prints 'Hook created' style message on success."""
        _fake_git_repo(tmp_path)
        cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=False))
        out = capsys.readouterr().out
        assert "Hook" in out or "hook" in out

    def test_human_already_installed_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Prints 'Ya instalado' when hook is already present."""
        _fake_git_repo(tmp_path)
        cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=False))
        capsys.readouterr()
        cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=False))
        out = capsys.readouterr().out
        assert "instalado" in out.lower()

    def test_add_to_stage_prints_extra_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Prints the extra stage message when add_to_stage=True."""
        _fake_git_repo(tmp_path)
        cmd_install_hook(_args(project=str(tmp_path), json=False, add_to_stage=True))
        out = capsys.readouterr().out
        assert "index.db" in out


# ──────────────────────────────────────────────
# main() — argument dispatch
# ──────────────────────────────────────────────


class TestMainEntry:
    """main() parses sys.argv and dispatches to sub-commands."""

    def test_no_command_exits_0(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Exits with code 0 and prints help when no sub-command is given."""
        with pytest.raises(SystemExit) as exc:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(sys, "argv", ["codeindex", "--project", str(tmp_path)])
                main()
        assert exc.value.code == 0

    def test_status_command_via_main(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """main() dispatches 'status' and produces output."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "argv", ["codeindex", "--project", str(tmp_path), "--json", "status"])
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
                ["codeindex", "--project", str(tmp_path), "--json", "index", str(src)],
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
                ["codeindex", "--project", str(tmp_path), "--json", "search", "Foo"],
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
                ["codeindex", "--project", str(tmp_path), "--json", "summary", "app.py"],
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
                    "codeindex",
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
                ["codeindex", "--project", str(tmp_path), "--json", "imports", "os"],
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
                    "codeindex",
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

    def test_install_skill_command_via_main(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """main() dispatches 'install-skill' and returns JSON with installed key."""
        import json

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                sys,
                "argv",
                ["codeindex", "--project", str(tmp_path), "--json", "install-skill"],
            )
            main()
        out = json.loads(capsys.readouterr().out)
        assert "installed" in out

    def test_install_hook_command_via_main(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """main() dispatches 'install-hook' and emits a JSON result."""
        import json

        _fake_git_repo(tmp_path)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                sys,
                "argv",
                ["codeindex", "--project", str(tmp_path), "--json", "install-hook"],
            )
            main()
        out = json.loads(capsys.readouterr().out)
        assert "status" in out
