"""Diff command: compare the current index against a base ref (PR review)."""

from __future__ import annotations

import os
import subprocess  # nosec B404 - runs git with a fixed argv, no shell
import sys
import tempfile
from pathlib import Path

import structlog

from ..config import load_config
from ..diff import (
    InvalidInputError,
    blocks_ci,
    check_comparable,
    compute_diff,
    validate_index,
)
from ..graph_store import GraphStore
from ..indexer import Indexer
from ..render.diff_markdown import render_diff_markdown
from .common import (
    _INDEX_ROOT_KEY,
    _debtector_dir,
    _get_store,
    _json_out,
    _open_store,
    _test_dirs,
    _test_prefixes,
)

log = structlog.get_logger()

_DIFF_SECTIONS = (
    ("new_cycles", "New cycles"),
    ("resolved_cycles", "Resolved cycles"),
    ("new_god_modules", "New god modules"),
    ("resolved_god_modules", "Resolved god modules"),
    ("new_sdp_violations", "New SDP violations"),
    ("resolved_sdp_violations", "Resolved SDP violations"),
    ("instability_regressions", "Instability regressions"),
    ("worsened_functions", "Functions with worse complexity"),
    ("improved_functions", "Functions with better complexity"),
    ("new_hotspots", "New hotspots"),
    ("worsened_hotspots", "Worsened hotspots"),
)


def _diff_item(item) -> str:
    if isinstance(item, dict) and "hotspot_score" in item:
        return (
            f"{item['file_path']}: churn {item['churn']}, "
            f"complexity {item['complexity']} ({item['severity']})"
        )
    if isinstance(item, dict) and "complexity_after" in item:
        return (
            f"{item['file_path']}: churn {item['churn']}, complexity "
            f"{item['complexity_before']} → {item['complexity_after']} "
            f"({item['severity_before']} → {item['severity']})"
        )
    if isinstance(item, list):
        return " → ".join(item) + " → ..."
    if isinstance(item, dict) and "qualified_name" in item:
        return f"{item['qualified_name']}: {item['before']} → {item['after']}"
    if isinstance(item, dict) and "metric" in item:
        return f"{item['file_path']}: {item['before']} → {item['after']}"
    if isinstance(item, dict):
        return f"{item['source']} → {item['target']}"
    return str(item)


def _git_out(cwd: str, *args: str) -> str:
    """Run ``git`` in *cwd* and return its stdout; :class:`InvalidInputError` if it fails."""
    try:
        proc = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["git", "-C", cwd, *args], capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, OSError) as e:
        detail = getattr(e, "stderr", "") or str(e)
        raise InvalidInputError(f"git {' '.join(args)} failed: {detail.strip()}") from e
    return proc.stdout.strip()


def _current_index_root(project: str) -> str:
    """Return the indexed directory of the project's index, relative to the project.

    Args:
        project: Path to the project root.

    Returns:
        The recorded ``index_root``, or ``"."`` for an empty (new) index.

    Raises:
        InvalidInputError: If the index has files but no recorded root (built by an
            older debtector): guessing it could rewrite every path, as in
            :func:`_auto_index`.
    """
    store = _get_store(project)
    try:
        rel = store.get_metadata(_INDEX_ROOT_KEY)
        if rel is None and store.get_all_files():
            raise InvalidInputError(
                "The current index has no recorded root (built by an older debtector); "
                "reindex it first: debtector index <dir>"
            )
    finally:
        store.close()
    return rel or "."


def _refresh_index(project: str) -> None:
    """Bring the project's index up to date, failing instead of comparing stale data.

    Unlike :func:`_auto_index`, a refresh that fails or skips files is an error: a
    diff against a partially updated index could hide a regression.

    Args:
        project: Path to the project root.

    Raises:
        InvalidInputError: If indexing raised or any file failed to index.
    """
    rel = _current_index_root(project)
    store = _get_store(project)
    try:
        try:
            stats = Indexer(store).index(str(Path(project) / rel), extra_paths=_test_dirs(project))
        except Exception as e:  # noqa: BLE001 - reported as invalid input, with the cause
            raise InvalidInputError(f"Could not refresh the current index: {e}") from e
        # A fresh index records its root, so later commands keep auto-refreshing it.
        store.set_metadata(_INDEX_ROOT_KEY, rel)
    finally:
        store.close()
    if stats["errors"]:
        raise InvalidInputError(
            f"Could not refresh the current index: {stats['errors']} file(s) failed "
            "(see .debtector/debtector.log)"
        )


def _index_base_ref(project: str, ref: str, db_path: str, worktree: Path) -> None:
    """Index *ref* of the project's repository into *db_path* through a temporary worktree.

    The worktree is always removed, also if indexing fails. The indexed directory
    is the same one (relative to the project) as in the current index, so the
    qualified names of both indexes match.

    Args:
        project: Path to the project root (inside a git repository).
        ref: Git ref to compare against (branch, tag or commit).
        db_path: Where to write the index of the ref.
        worktree: Directory for the temporary worktree; must not exist.

    Raises:
        InvalidInputError: If *project* is not in a git repository or *ref* does not exist.
    """
    # Physical path: git reports the real toplevel, and a symlinked alias would give a
    # relative path with ``..`` that escapes the worktree.
    project = os.path.realpath(project)
    toplevel = _git_out(project, "rev-parse", "--show-toplevel")
    try:
        _git_out(project, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except InvalidInputError as e:
        raise InvalidInputError(f"Unknown git ref: {ref}") from e
    submodules = _git_out(project, "submodule", "status", "--recursive")
    if any(line and not line.startswith("-") for line in submodules.splitlines()):
        # A new worktree leaves submodules empty: the base would miss their files.
        raise InvalidInputError(
            "--base does not support repositories with initialized submodules; "
            "index both revisions and run: debtector diff <db_base> <db_pr>"
        )
    real_top = os.path.realpath(toplevel)
    rel_project = Path(os.path.relpath(project, real_top))
    rel_root = _current_index_root(project)
    indexed = os.path.realpath(Path(project) / rel_root)
    if os.path.commonpath([indexed, real_top]) != real_top:
        # The worktree only contains the repository: the base would be empty.
        raise InvalidInputError(
            f"The indexed directory {indexed} is outside the git repository {real_top}; "
            "--base can only compare directories inside it"
        )
    try:
        # Inside the guard: a failing post-checkout hook makes ``worktree add`` report an
        # error after the worktree is already registered.
        _git_out(project, "worktree", "add", "--detach", str(worktree), ref)
        wt_project = worktree / rel_project
        store = GraphStore(db_path)
        try:
            store.test_prefixes = _test_prefixes(project, str(Path(project) / rel_root))
            extra = [str(wt_project / os.path.relpath(d, project)) for d in _test_dirs(project)]
            stats = Indexer(store).index(str(wt_project / rel_root), extra_paths=extra)
            if stats["errors"]:
                raise InvalidInputError(
                    f"Could not index {ref}: {stats['errors']} file(s) failed "
                    "(see .debtector/debtector.log)"
                )
            store.set_metadata(_INDEX_ROOT_KEY, rel_root)
        finally:
            store.close()
    finally:
        try:
            _git_out(project, "worktree", "remove", "--force", str(worktree))
        except InvalidInputError:
            # Never registered (``add`` failed early) or already gone: do not mask the
            # original error; ``prune`` drops a registration whose directory is gone.
            log.warning("diff_worktree_remove_failed", worktree=str(worktree), exc_info=True)
            _git_out(project, "worktree", "prune")


def cmd_diff(args) -> None:
    """Compare two indexes and report the architectural changes.

    Args:
        args: Parsed argument namespace. Expected attributes: ``project``
            (str, where ``debtector.toml`` lives), ``json`` (bool), ``db_base``
            and ``db_pr`` (str, paths to the two indexes).

    Exits with 2 if the inputs are not valid, and with 1 if something new has
    ``error`` severity in ``[metrics.severity]`` (D-0008).
    """
    cfg = load_config(args.project)
    base_ref = getattr(args, "base_ref", None)
    try:
        if base_ref and (args.db_base or args.db_pr):
            raise InvalidInputError("--base cannot be combined with index paths")
        if not base_ref and not (args.db_base and args.db_pr):
            raise InvalidInputError("pass --base <ref>, or the two indexes to compare")
        with tempfile.TemporaryDirectory(prefix="debtector-diff-") as tmp:
            db_base, db_pr = args.db_base, args.db_pr
            if base_ref:
                db_base = str(Path(tmp) / "base.db")
                _index_base_ref(args.project, base_ref, db_base, Path(tmp) / "worktree")
                _refresh_index(args.project)
                db_pr = str(_debtector_dir(args.project) / "index.db")
            validate_index(db_base)
            validate_index(db_pr)
            base, pr = _open_store(db_base, args.project), _open_store(db_pr, args.project)
            try:
                check_comparable(base, pr)
                result = compute_diff(base, pr, cfg, args.project)
            finally:
                base.close()
                pr.close()
    except InvalidInputError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    blocking = blocks_ci(result, cfg.metrics.severity)

    if args.json:
        _json_out(result)
    elif getattr(args, "format", "text") == "markdown":
        print(render_diff_markdown(result), end="")
    else:
        if not any(result[key] for key, _ in _DIFF_SECTIONS):
            print("No architectural changes")
        for key, title in _DIFF_SECTIONS:
            if result[key]:
                print(f"\n{title} ({len(result[key])}):")
                for item in result[key]:
                    print(f"   {_diff_item(item)}")
        for item in result["skipped"]:
            print(f"\nSkipped {item['section']}: {item['reason']}")
    if blocking:
        sys.exit(1)
