"""Behavioural analysis based on git history.

Extracts metrics such as churn, hotspots, temporal coupling and bus factor
from ``git log`` and ``git blame``. These signals complement the structural
coupling graph with evidence of which modules generate the most technical
debt in practice.

No function in this module writes to the database; all of them are
read-only queries against the project's git repository.
"""

from __future__ import annotations

import itertools
import re
import subprocess  # nosec B404 — required for git invocation; no user input reaches subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import structlog

log = structlog.get_logger()

# Pattern that recognises a SHA-1 commit hash (40 hex chars)
_HASH_RE = re.compile(r"^[0-9a-f]{40}$")

# Rename in --numstat with a common part: ``src/{old => new}/a.py``
_RENAME_BRACES_RE = re.compile(r"^(.*)\{(.*) => (.*)\}(.*)$")

# Bus factor threshold: minimum authors needed to cover X% of the code
_BUS_FACTOR_COVERAGE = 0.80


# ──────────────────────────────────────────────
# Public dataclasses
# ──────────────────────────────────────────────


@dataclass
class ChurnMetrics:
    """Activity of a file in the git history.

    Attributes:
        file_path: Relative path of the file.
        commits: Number of distinct commits that touch the file.
        lines_added: Total lines added across all commits.
        lines_deleted: Total lines deleted across all commits.
    """

    file_path: str
    commits: int
    lines_added: int
    lines_deleted: int


@dataclass
class HotspotMetrics:
    """Intersection of churn and structural coupling.

    A hotspot is a file with high change activity *and* high coupling
    with other modules. It is the most reliable signal of actionable
    technical debt.

    Attributes:
        file_path: Relative path of the file.
        churn: Number of commits that touch the file.
        coupling: fan_in + fan_out of the module in the structural graph.
        hotspot_score: churn × coupling — technical debt ranking.
        severity: Severity level for health score aggregation.
    """

    file_path: str
    churn: int
    coupling: float
    hotspot_score: float
    severity: str = "medium"


@dataclass
class TemporalCoupling:
    """Pair of files that frequently change together.

    Detects implicit dependencies between modules that have no direct
    import but that the team modifies in a coordinated way.

    Attributes:
        file_a: Path of the first file (lexicographically smaller).
        file_b: Path of the second file.
        shared_commits: Commits in which both files changed.
        coupling_ratio: shared_commits / min(commits_a, commits_b).
            1.0 means perfect coupling.
    """

    file_a: str
    file_b: str
    shared_commits: int
    coupling_ratio: float


@dataclass
class BusFactorMetrics:
    """Risk of knowledge concentrated in a single author.

    Attributes:
        file_path: Relative path of the file.
        top_author: Author with the most surviving lines according to ``git blame``.
        top_author_pct: Percentage of lines owned by the dominant author.
        bus_factor: Minimum number of authors needed to cover 80% of the code.
            1 = single point of failure.
    """

    file_path: str
    top_author: str
    top_author_pct: float
    bus_factor: int


# ──────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────


def _run_git(cmd: list[str], cwd: str | Path) -> str:
    """Run a git command and return its stdout as text.

    Args:
        cmd: Command parts (e.g. ``["git", "log", "--numstat"]``).
        cwd: Directory in which to run git.

    Returns:
        Standard output decoded as a UTF-8 string.

    Raises:
        RuntimeError: If git is not available or the directory is not a repo.
    """
    try:
        result = subprocess.run(  # nosec B603 — cmd is constructed internally, never from user input
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except FileNotFoundError as exc:
        raise RuntimeError(
            "git is not available on the PATH. Install git to use this feature."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Error running '{' '.join(cmd)}': {exc.stderr.strip()}") from exc


def _is_hash(line: str) -> bool:
    """Return True if the line is a SHA-1 commit hash."""
    return bool(_HASH_RE.match(line))


def _split_rename(path: str) -> tuple[str, str] | None:
    """Split a ``--numstat`` rename path into ``(old, new)``.

    git writes ``src/{old => new}/a.py`` or ``old.py => new.py``; one side
    of the ``{}`` may be empty (``{ => sub}/a.py``).

    Returns:
        ``(old, new)``, or ``None`` if *path* is not a rename.
    """
    m = _RENAME_BRACES_RE.match(path)
    if m:
        pre, old, new, post = m.groups()
        return (
            re.sub("/+", "/", pre + old + post).lstrip("/"),
            re.sub("/+", "/", pre + new + post).lstrip("/"),
        )
    if " => " in path:
        old, new = path.split(" => ", 1)
        return old, new
    return None


def _log_changes(
    project_root: str | Path,
    since: str | None = None,
) -> list[tuple[str, list[tuple[str, int, int]]]]:
    """Read ``git log --numstat`` with renames resolved to the current name.

    ``--relative`` keeps paths relative to *project_root*, which may be a
    subdirectory of the repo (e.g. ``debtector index ./src``), as in the graph.
    The log goes from the newest commit to the oldest: when a rename appears,
    the older commits of the old path are attributed to the current path.

    Args:
        project_root: Directory from which to run git.
        since: Optional date filter (e.g. ``"6 months ago"``).

    Returns:
        ``(hash, [(current_path, added, deleted), ...])`` per commit.
        Binary files count with 0 lines.
    """
    cmd = ["git", "log", "--numstat", "--relative", "-M", "--format=%H"]
    if since:
        cmd.append(f"--since={since}")

    output = _run_git(cmd, project_root)

    current_name: dict[str, str] = {}
    commits: list[tuple[str, list[tuple[str, int, int]]]] = []

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_hash(line):
            commits.append((line, []))
            continue
        if not commits or "\t" not in line:
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        added_str, deleted_str, path = parts
        try:
            added, deleted = int(added_str), int(deleted_str)
        except ValueError:
            # Binary files show "-"
            added = deleted = 0
        rename = _split_rename(path)
        if rename:
            old, new = rename
            path = current_name.get(new, new)
            current_name[old] = path
        else:
            path = current_name.get(path, path)
        commits[-1][1].append((path, added, deleted))

    return commits


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────


def parse_churn(
    project_root: str | Path,
    since: str | None = None,
) -> list[ChurnMetrics]:
    """Parse ``git log --numstat`` to compute churn per file.

    Churn measures how many times each file has been modified. Binary
    files (which show ``-`` in the line columns) are included with
    0 lines.

    Args:
        project_root: Root directory of the git repository.
        since: Optional date filter (e.g. ``"6 months ago"``).

    Returns:
        List of :class:`ChurnMetrics` sorted by number of commits,
        descending. Empty if there is no history.
    """
    commits_per_file: dict[str, set[str]] = defaultdict(set)
    lines_added: dict[str, int] = defaultdict(int)
    lines_deleted: dict[str, int] = defaultdict(int)

    for commit_hash, changes in _log_changes(project_root, since=since):
        for file_path, added, deleted in changes:
            commits_per_file[file_path].add(commit_hash)
            lines_added[file_path] += added
            lines_deleted[file_path] += deleted

    results = [
        ChurnMetrics(
            file_path=fp,
            commits=len(hashes),
            lines_added=lines_added[fp],
            lines_deleted=lines_deleted[fp],
        )
        for fp, hashes in commits_per_file.items()
    ]
    return sorted(results, key=lambda m: m.commits, reverse=True)


def compute_hotspots(
    store: GraphStore,  # type: ignore[name-defined]  # noqa: F821
    project_root: str | Path,
    since: str | None = None,
    limit: int | None = None,
) -> list[HotspotMetrics]:
    """Combine churn with structural coupling to identify hotspots.

    The hotspot score is ``churn × (fan_in + fan_out)``. Only files that
    have git history *and* are indexed in the graph are included.

    Args:
        store: :class:`~debtector.graph_store.GraphStore` holding the index.
        project_root: Root directory of the git repository.
        since: Optional date filter for churn.
        limit: Maximum number of results. ``None`` returns all of them.

    Returns:
        List of :class:`HotspotMetrics` sorted by score, descending.
    """
    from .metrics import compute_metrics

    module_metrics = compute_metrics(store)
    if not module_metrics:
        return []

    churn_list = parse_churn(project_root, since=since)
    churn_map = {c.file_path: c for c in churn_list}

    # Iterate over currently-indexed files so renamed/deleted files from git
    # history don't pollute results with coupling=0.
    coupling_map = {m.file_path: m.fan_in + m.fan_out for m in module_metrics}

    hotspots: list[HotspotMetrics] = []
    for file_path, coupling in coupling_map.items():
        churn_data = churn_map.get(file_path)
        if churn_data is None:
            continue
        score = churn_data.commits * coupling
        hotspots.append(
            HotspotMetrics(
                file_path=file_path,
                churn=churn_data.commits,
                coupling=coupling,
                hotspot_score=score,
            )
        )

    hotspots.sort(key=lambda h: h.hotspot_score, reverse=True)
    if limit is not None:
        hotspots = hotspots[:limit]

    log.debug("hotspots_computed", total=len(hotspots))
    return hotspots


def compute_temporal_coupling(
    project_root: str | Path,
    min_shared: int = 5,
    min_ratio: float = 0.3,
    since: str | None = None,
) -> list[TemporalCoupling]:
    """Find pairs of files that frequently change together.

    Detects implicit dependencies: modules that the team modifies in a
    coordinated way even though they have no direct ``import`` between them.

    Args:
        project_root: Root directory of the git repository.
        min_shared: Minimum shared commits required to report a pair.
        min_ratio: Minimum ratio ``shared / min(commits_a, commits_b)``.
        since: Optional date filter.

    Returns:
        List of :class:`TemporalCoupling` sorted by shared
        commits, descending.
    """
    changes = _log_changes(project_root, since=since)
    # Deleted files only exist in the history: drop them.
    tracked = set(_run_git(["git", "ls-files"], project_root).splitlines())

    # commit_hash → modified files (deduplicated: a rename and its edit)
    commit_files: dict[str, set[str]] = {}
    # file → set of commits that touch it
    file_commits: dict[str, set[str]] = defaultdict(set)

    for commit_hash, files in changes:
        current = {path for path, _, _ in files if path in tracked}
        commit_files[commit_hash] = current
        for path in current:
            file_commits[path].add(commit_hash)

    # Count shared commits for each pair of files
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for files in commit_files.values():
        for a, b in itertools.combinations(sorted(files), 2):
            pair_counts[(a, b)] += 1

    results: list[TemporalCoupling] = []
    for (file_a, file_b), shared in pair_counts.items():
        if shared < min_shared:
            continue
        commits_a = len(file_commits[file_a])
        commits_b = len(file_commits[file_b])
        denom = min(commits_a, commits_b)
        ratio = shared / denom if denom > 0 else 0.0
        if ratio < min_ratio:
            continue
        results.append(
            TemporalCoupling(
                file_a=file_a,
                file_b=file_b,
                shared_commits=shared,
                coupling_ratio=round(ratio, 4),
            )
        )

    results.sort(key=lambda t: t.shared_commits, reverse=True)
    log.debug("temporal_coupling_computed", pairs=len(results))
    return results


def is_shallow_repository(project_root: str | Path) -> bool:
    """Return whether the repository is a shallow clone (``--depth``).

    Args:
        project_root: Directory inside the git repository.

    Returns:
        ``True`` if the history is truncated.

    Raises:
        RuntimeError: If git is not available or this is not a repository.
    """
    return _run_git(["git", "rev-parse", "--is-shallow-repository"], project_root).strip() == "true"


def list_authors(project_root: str | Path) -> set[str]:
    """Return the distinct authors in the history of the whole repository.

    Uses ``git log`` (not ``git blame``): it does not count uncommitted lines
    nor depend on which lines survive. Respects ``.mailmap``. Ignores bot
    accounts (names ending in ``[bot]``, e.g. ``github-actions[bot]``).
    Counts the whole repository, not just the indexed subdirectory: someone
    who contributes outside it is still a member of the team.

    Args:
        project_root: Directory inside the git repository (may be a
            subdirectory; the repository root is resolved).

    Returns:
        Set of author names. Empty if there is no history.

    Raises:
        RuntimeError: If git is not available or this is not a repository.
    """
    top = _run_git(["git", "rev-parse", "--show-toplevel"], project_root).strip()
    output = _run_git(["git", "log", "--format=%aN"], top)
    names = {line.strip() for line in output.splitlines() if line.strip()}
    return {n for n in names if not n.endswith("[bot]")}


def compute_bus_factor(
    store: GraphStore,  # type: ignore[name-defined]  # noqa: F821
    project_root: str | Path,
) -> list[BusFactorMetrics]:
    """Compute the bus factor per file using ``git blame``.

    Only processes files present in the graph index. Files for which
    ``git blame`` fails (e.g. new files without commits) are skipped
    with a warning in the log.

    Args:
        store: :class:`~debtector.graph_store.GraphStore` holding the index.
        project_root: Root directory of the git repository.

    Returns:
        List of :class:`BusFactorMetrics` sorted by bus factor,
        ascending (most at-risk first), then by the dominant author's
        percentage, descending.
    """
    indexed_files = store.get_all_files()
    results: list[BusFactorMetrics] = []

    for file_path in sorted(indexed_files):
        try:
            output = _run_git(
                ["git", "blame", "--line-porcelain", file_path],
                project_root,
            )
        except RuntimeError:
            log.warning("bus_factor_blame_failed", file_path=file_path)
            continue

        author_lines: dict[str, int] = defaultdict(int)
        for line in output.splitlines():
            # "author <name>" lines (not "author-mail", "author-time", etc.)
            if line.startswith("author ") and not line.startswith("author-"):
                author = line[len("author ") :].strip()
                author_lines[author] += 1

        if not author_lines:
            continue

        total = sum(author_lines.values())
        sorted_authors = sorted(author_lines.items(), key=lambda x: x[1], reverse=True)
        top_author, top_count = sorted_authors[0]
        top_pct = top_count / total * 100

        # Bus factor: minimum authors needed to cover >= 80% of the lines
        cumulative = 0
        bus_factor = 0
        for _, count in sorted_authors:
            cumulative += count
            bus_factor += 1
            if cumulative / total >= _BUS_FACTOR_COVERAGE:
                break

        results.append(
            BusFactorMetrics(
                file_path=file_path,
                top_author=top_author,
                top_author_pct=round(top_pct, 1),
                bus_factor=bus_factor,
            )
        )

    results.sort(key=lambda b: (b.bus_factor, -b.top_author_pct))
    log.debug("bus_factor_computed", files=len(results))
    return results
