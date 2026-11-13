"""
Coupling metrics module for Debtector.

Computes structural metrics at module (file) level:

- Fan-in  (Ca): number of modules that import this module.
- Fan-out (Ce): number of modules this module imports.
- Instability (I = Ce / (Ca + Ce)): 0 = very stable, 1 = very unstable.
- Cycles: strongly connected components of size > 1 over
  IMPORTS_FROM and CALLS edges.
- God modules: statistical Ca outliers above the project's 90th percentile
  and with an absolute minimum Ca (``god_module_min_ca``).
- SDP violations: dependencies from a stable module to a more unstable one.

Metrics are computed over the graph's IMPORTS_FROM edges (USES_TYPE edges do
not count: the import of a type already counts its module, D-0012). Ca and Ce count
distinct internal modules: imports that do not resolve to an indexed File
(external packages) are ignored, and each (importer, imported) pair counts
once however many import statements there are (D-0012).
"""

from __future__ import annotations

import posixpath
import statistics
from collections import defaultdict
from dataclasses import dataclass

from .graph_store import GraphStore
from .models import EdgeKind, NodeKind

# Version of the Ca/Ce computation. Bump it when a change makes the numbers
# incomparable with those of an older baseline (D-0014).
METRICS_VERSION = 11

# Edge kinds considered for cycle detection
_CYCLE_EDGE_KINDS = (EdgeKind.IMPORTS_FROM, EdgeKind.CALLS)

# ──────────────────────────────────────────────
# Edge weights in the Ca/Ce computation
#
# All constants are public to ease tuning during experiments and in
# tests. Changing a weight here affects compute_metrics globally without
# touching the computation logic.
# ──────────────────────────────────────────────

#: Weight of IMPORTS_FROM edges: explicit structural coupling.
IMPORTS_FROM_WEIGHT: float = 1.0


@dataclass
class ModuleMetrics:
    """Coupling metrics for a single module (file).

    Args:
        file_path: Relative path of the file.
        fan_in: Fan-in (Ca) — weighted sum of incoming edges. IMPORTS_FROM
            edges count 1.0; USES_TYPE edges do not count.
        fan_out: Fan-out (Ce) — weighted sum of outgoing edges. Same weighting
            scheme as ``fan_in``.
        instability: I = Ce / (Ca + Ce). 0.0 if the module is isolated.
    """

    file_path: str
    fan_in: float
    fan_out: float
    instability: float


def _build_module_map(file_paths: set[str]) -> dict[str, str]:
    """Build a module-name → file_path map for import resolution.

    Allows translating IMPORTS_FROM edge targets (e.g. ``"debtector.models"``,
    ``".graph_store"``) to the real indexed file paths (e.g.
    ``"debtector/models.py"``), so that Ca reflects internal dependencies.

    Generates the following keys for each file path:

    - Dotted name: ``"debtector/models.py"`` → ``"debtector.models"``
    - ``__init__.py``: ``"debtector/parser/__init__.py"`` → ``"debtector.parser"``
    - Python files also get their name from the top of their package (the highest
      directory chain with ``__init__.py`` in the index): ``"src/pkg/mod.py"`` →
      ``"pkg.mod"``; a file outside any package is named by its own name
      (``"scripts/utils.py"`` → ``"utils"``). A name shared by several files is not
      mapped (D-0016). Names from the repo root keep priority.

    Args:
        file_paths: Set of file paths of the indexed File nodes.

    Returns:
        Dictionary of module name → file path.
    """
    module_map: dict[str, str] = {}
    for fp in file_paths:
        # "debtector/models.py" → "debtector.models"
        dot_name = fp.replace("/", ".").replace("\\", ".")
        for ext in (".py", ".js", ".ts", ".jsx", ".tsx"):
            if dot_name.endswith(ext):
                dot_name = dot_name[: -len(ext)]
                break
        # Strip the .__init__ suffix for packages
        if dot_name.endswith(".__init__"):
            dot_name = dot_name[:-9]
        module_map[dot_name] = fp

    pkg_names: dict[str, set[str]] = {}
    for fp in file_paths:
        name = _python_package_name(fp, file_paths)
        if name:
            pkg_names.setdefault(name, set()).add(fp)
    for name, owners in pkg_names.items():
        if len(owners) == 1:
            module_map.setdefault(name, next(iter(owners)))
    return module_map


def _python_package_name(fp: str, file_paths: set[str]) -> str:
    """Return the module name of a Python file from the root of its package."""
    if not fp.endswith(".py"):
        return ""
    parts = fp.replace("\\", "/").split("/")
    stem = parts[-1][:-3]
    dirs = parts[:-1]
    pkg: list[str] = []
    while dirs and "/".join([*dirs, "__init__.py"]) in file_paths:
        pkg.insert(0, dirs.pop())
    if stem != "__init__":
        pkg.append(stem)
    return ".".join(pkg)


def _resolve_import_target(
    target: str,
    source_file: str,
    module_map: dict[str, str],
    files: set[str] | None = None,
) -> str:
    """Resolve an IMPORTS_FROM target to a file path if it is an internal module.

    Handles three forms (since ``PARSER_VERSION`` 5 relative imports keep their dots,
    so a bare name such as ``"json"`` is always absolute and never guessed as a sibling):

    1. Absolute dotted name: ``"debtector.models"``
    2. Relative import with leading dot: ``".models"`` (from ``"debtector/cli.py"``)
    3. Already an indexed file path: returned as is.

    Args:
        target: Value stored in ``edges.target_qualified`` for the edge.
        source_file: ``file_path`` of the file that contains the edge.
        module_map: Map built by :func:`_build_module_map`.
        files: Indexed file paths. Defaults to the values of ``module_map``, which
            lacks the files whose module name collides (``x.js`` and ``x.ts``).

    Returns:
        File path of the imported module if resolved; *target* unchanged otherwise.
    """
    # Direct match (already a file path)
    if target in module_map.values():
        return target

    # Absolute dotted name: "debtector.models"
    if target in module_map:
        return module_map[target]

    # Relative import with explicit dot: ".models", "..utils"
    if target.startswith("."):
        parts = source_file.replace("\\", "/").split("/")
        dots = len(target) - len(target.lstrip("."))
        base_parts = parts[:-dots] if dots <= len(parts) else []
        rel_name = target.lstrip(".")
        if base_parts:
            abs_module = ".".join(base_parts) + ("." + rel_name if rel_name else "")
        else:
            abs_module = rel_name
        if abs_module in module_map:
            return module_map[abs_module]

    # JS/TS relative path: "./b", "../lib/b" (with or without extension or index file)
    if target.startswith(("./", "../")):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(source_file), target))
        values = files if files is not None else set(module_map.values())
        # TypeScript: "./x.js" may name x.ts, "./c.jsx" may name c.tsx (exact file wins)
        if base in values:
            return base
        for js_ext, ts_ext in ((".js", ".ts"), (".jsx", ".tsx")):
            if base.endswith(js_ext) and base[: -len(js_ext)] + ts_ext in values:
                return base[: -len(js_ext)] + ts_ext
        for ext in ("", ".js", ".ts", ".jsx", ".tsx"):
            for cand in (base + ext, f"{base}/index{ext}"):
                if cand in values:
                    return cand

    return target  # unresolved → external package


def compute_metrics(store: GraphStore) -> list[ModuleMetrics]:
    """Compute Ca, Ce and I for all indexed modules.

    Only ``File`` nodes take part as units of analysis. Imports of external
    packages (e.g. ``"flask"``) have no File node and are ignored; repeated
    imports of the same module count once.

    IMPORTS_FROM edge targets are resolved from module name to file path
    via :func:`_resolve_import_target`, so that Ca correctly reflects the
    project's internal dependencies.

    Args:
        store: GraphStore with the project index.

    Returns:
        List of :class:`ModuleMetrics`, one entry per indexed file.
        Empty list if the index is empty.
    """
    conn = store._conn

    # Get all File nodes. Files outside the indexed root (``../...``) are
    # the tests added via ``test_paths``: they are not production modules
    # and their edges do not count towards Ca/Ce.
    file_rows = conn.execute(
        "SELECT qualified_name FROM nodes WHERE kind = ? AND file_path NOT LIKE '../%'",
        (NodeKind.FILE,),
    ).fetchall()

    if not file_rows:
        return []

    # Test files are not modules and are not dependents either (D-0015).
    file_rows = [r for r in file_rows if not store.is_test_path(r["qualified_name"])]
    file_paths: set[str] = {r["qualified_name"] for r in file_rows}
    module_map = _build_module_map(file_paths)

    # Ce per file: outgoing IMPORTS_FROM edges (weight 1.0)
    # Ca per file: IMPORTS_FROM edges with module-name resolution
    ce_map: dict[str, float] = {}
    ca_map: dict[str, float] = {}

    import_rows = conn.execute(
        "SELECT source_qualified, target_qualified, file_path FROM edges"
        " WHERE kind = ? AND file_path NOT LIKE '../%'",
        (EdgeKind.IMPORTS_FROM,),
    ).fetchall()

    seen_pairs: set[tuple[str, str]] = set()
    for r in import_rows:
        src = r["source_qualified"]
        resolved = _resolve_import_target(
            r["target_qualified"], r["file_path"], module_map, file_paths
        )
        if src not in file_paths or resolved not in file_paths or (src, resolved) in seen_pairs:
            continue
        seen_pairs.add((src, resolved))
        ce_map[src] = ce_map.get(src, 0.0) + IMPORTS_FROM_WEIGHT
        ca_map[resolved] = ca_map.get(resolved, 0.0) + IMPORTS_FROM_WEIGHT

    results: list[ModuleMetrics] = []
    for row in file_rows:
        qn: str = row["qualified_name"]
        ce = ce_map.get(qn, 0.0)
        ca = ca_map.get(qn, 0.0)
        total = ca + ce
        instability = ce / total if total > 0 else 0.0
        results.append(
            ModuleMetrics(
                file_path=qn,  # for File nodes, qualified_name == file_path
                fan_in=ca,
                fan_out=ce,
                instability=instability,
            )
        )

    return results


def find_cycles(store: GraphStore) -> list[list[str]]:
    """Detect cycles in the graph using Tarjan's algorithm (SCCs).

    Considers ``IMPORTS_FROM`` and ``CALLS`` edges. Only includes nodes that
    exist as ``File`` in the index; external targets (third-party packages
    with no node of their own) are ignored.

    Args:
        store: GraphStore with the project index.

    Returns:
        List of cycles. Each cycle is a list of the ``qualified_name`` of the
        nodes that form the strongly connected component.
        Empty list if there are no cycles.
    """
    conn = store._conn

    # Set of indexed File nodes (external ones are discarded)
    file_set: set[str] = {
        r["qualified_name"]
        for r in conn.execute(
            "SELECT qualified_name FROM nodes WHERE kind = ?", (NodeKind.FILE,)
        ).fetchall()
        if not store.is_test_path(r["qualified_name"])  # D-0015
    }

    if not file_set:
        return []

    # Build the adjacency list with indexed nodes only
    placeholders = ",".join("?" * len(_CYCLE_EDGE_KINDS))
    rows = conn.execute(
        f"SELECT kind, source_qualified, target_qualified, file_path FROM edges"  # nosec B608
        f" WHERE kind IN ({placeholders})",
        list(_CYCLE_EDGE_KINDS),
    ).fetchall()

    # IMPORTS_FROM targets are module names ("pkg.b", "c"): resolve them to files,
    # as compute_metrics and sdp_violations do, or no real import cycle is found.
    module_map = _build_module_map(file_set)
    adj: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        src, tgt = r["source_qualified"], r["target_qualified"]
        if r["kind"] == EdgeKind.IMPORTS_FROM:
            tgt = _resolve_import_target(tgt, r["file_path"], module_map, file_set)
        if src in file_set and tgt in file_set and tgt != src:
            adj[src].append(tgt)

    # Iterative Tarjan algorithm for strongly connected components.
    # The explicit iterative version (worklist) is used instead of the
    # recursive one to avoid RecursionError on graphs with long dependency
    # chains.
    #
    # Per-node iterator state: index into adj[node] of the next neighbor
    # still to be processed. When the neighbors are exhausted, the node's
    # SCC check is done just like in the recursive version.
    index_counter = [0]
    scc_stack: list[str] = []  # Tarjan stack
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[list[str]] = []

    # worklist: (node, neighbor-iterator). Simulates the call stack of the
    # recursive version without consuming Python stack frames.
    for root in file_set:
        if root in index:
            continue

        worklist: list[tuple[str, int]] = [(root, 0)]
        index[root] = index_counter[0]
        lowlink[root] = index_counter[0]
        index_counter[0] += 1
        scc_stack.append(root)
        on_stack[root] = True

        while worklist:
            node, nei_idx = worklist[-1]
            neighbors = adj.get(node, [])

            if nei_idx < len(neighbors):
                # Advance to the next neighbor without popping the frame
                worklist[-1] = (node, nei_idx + 1)
                neighbor = neighbors[nei_idx]

                if neighbor not in index:
                    # Discover neighbor: "recursive call"
                    index[neighbor] = index_counter[0]
                    lowlink[neighbor] = index_counter[0]
                    index_counter[0] += 1
                    scc_stack.append(neighbor)
                    on_stack[neighbor] = True
                    worklist.append((neighbor, 0))
                elif on_stack.get(neighbor, False):
                    lowlink[node] = min(lowlink[node], index[neighbor])
            else:
                # All neighbors processed: "return from recursive call"
                worklist.pop()
                if worklist:
                    parent = worklist[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])

                # Detect SCC root
                if lowlink[node] == index[node]:
                    scc: list[str] = []
                    while True:
                        w = scc_stack.pop()
                        on_stack[w] = False
                        scc.append(w)
                        if w == node:
                            break
                    if len(scc) > 1:
                        sccs.append(scc)

    return sccs


@dataclass
class InheritanceMetrics:
    """Inheritance metrics for a class.

    Args:
        qualified_name: Unique identifier of the class.
        depth: Depth in the inheritance hierarchy (0 = root class).
        children: Number of classes that inherit directly from this one.
    """

    qualified_name: str
    depth: int
    children: int


def inheritance_metrics(store: GraphStore) -> list[InheritanceMetrics]:
    """Compute inheritance depth and number of children for each class.

    Walks the graph's ``INHERITS`` edges. Depth is computed as the longest
    path from the hierarchy root to the class. Inheritance cycles (invalid
    in Python/JS) are cut when an already visited node is detected.

    Args:
        store: GraphStore with the project index.

    Returns:
        List of :class:`InheritanceMetrics`, one per indexed class.
        Empty list if there are no classes in the index.
    """
    conn = store._conn

    # Get all nodes with kind=Class
    class_rows = conn.execute(
        "SELECT qualified_name FROM nodes WHERE kind = ?",
        (NodeKind.CLASS,),
    ).fetchall()

    if not class_rows:
        return []

    class_set: set[str] = {r["qualified_name"] for r in class_rows}

    # INHERITS edges: source=child, target=parent
    edge_rows = conn.execute(
        "SELECT source_qualified, target_qualified FROM edges WHERE kind = ?",
        (EdgeKind.INHERITS,),
    ).fetchall()

    # children_map[parent] = number of direct children
    children_map: dict[str, int] = defaultdict(int)
    # parent_map[child] = qualified_name of the parent (may be external)
    parent_map: dict[str, str] = {}

    for r in edge_rows:
        child, parent = r["source_qualified"], r["target_qualified"]
        parent_map[child] = parent
        if parent in class_set:
            children_map[parent] += 1

    def _depth(qn: str, visited: set[str]) -> int:
        """Compute the depth recursively, cutting cycles."""
        if qn in visited:
            return 0
        parent = parent_map.get(qn)
        if parent is None:
            return 0
        visited.add(qn)
        return 1 + _depth(parent, visited)

    results: list[InheritanceMetrics] = []
    for qn in class_set:
        results.append(
            InheritanceMetrics(
                qualified_name=qn,
                depth=_depth(qn, set()),
                children=children_map.get(qn, 0),
            )
        )

    return results


def percentile_threshold(values: list[float], percentile: float) -> float:
    """Return the ``percentile``-th percentile of *values*.

    Shared by god-module detection and the audit hotspot filter so both use
    the same project-relative cut.

    Args:
        values: Sample; at least 2 points are needed for a real percentile.
        percentile: Percentile in ``[1, 99]``.

    Returns:
        The percentile value; with a single point, that point.

    Raises:
        ValueError: If *percentile* is outside ``[1, 99]`` or *values* is empty.
    """
    if not (1 <= percentile <= 99):
        raise ValueError(f"percentile must be in [1, 99], got {percentile}")
    if not values:
        raise ValueError("values must not be empty")
    if len(values) < 2:
        return values[0]
    # "inclusive" keeps the result within [min, max]; "exclusive" extrapolates on small samples.
    return statistics.quantiles(values, n=100, method="inclusive")[int(percentile) - 1]


@dataclass
class SdpViolation:
    """Dependency ``source → target`` that violates the Stable Dependencies Principle.

    Args:
        source: Importing module (the "more stable" one).
        target: Imported module, more unstable than ``source``.
        source_instability: I of the importing module.
        target_instability: I of the imported module.
    """

    source: str
    target: str
    source_instability: float
    target_instability: float


_FACADE_NAMES = frozenset({"__init__.py", "index.js", "index.ts", "index.jsx", "index.tsx"})


def _pure_facades(store: GraphStore, files: set[str]) -> set[str]:
    """Return the ``__init__.py`` and ``index.{js,ts,jsx,tsx}`` files with no class or function."""
    inits = [f for f in files if posixpath.basename(f) in _FACADE_NAMES]
    if not inits:
        return set()
    defining: set[str] = set()
    for i in range(0, len(inits), 450):
        batch = inits[i : i + 450]
        marks = ",".join("?" * len(batch))
        rows = store._conn.execute(
            f"SELECT DISTINCT file_path FROM nodes WHERE kind IN (?, ?, ?)"  # nosec B608
            f" AND file_path IN ({marks})",
            (NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD, *batch),
        ).fetchall()
        defining.update(r["file_path"] for r in rows)
    return set(inits) - defining


def sdp_violations(store: GraphStore, margin: float = 0.0) -> list[SdpViolation]:
    """Detect violations of the Stable Dependencies Principle (SDP).

    A violation is an ``IMPORTS_FROM`` edge between two indexed production
    modules ``A → B`` with ``I(B) > I(A) + margin``: a more stable module
    depends on a less stable one. The same resolved edges as
    :func:`compute_metrics` use for Ca/Ce are used. ``USES_TYPE`` edges are
    not considered: their target is a type name, not a resolvable module.

    Args:
        store: GraphStore with the project index.
        margin: Minimum (strict) difference in I to count as a violation.

    Returns:
        Unique violations sorted by ``(source, target)``.
    """
    metrics = compute_metrics(store)
    if not metrics:
        return []
    instability = {m.file_path: m.instability for m in metrics}
    module_map = _build_module_map(set(instability))
    facades = _pure_facades(store, set(instability))

    rows = store._conn.execute(
        "SELECT source_qualified, target_qualified, file_path FROM edges"
        " WHERE kind = ? AND file_path NOT LIKE '../%'",
        (EdgeKind.IMPORTS_FROM,),
    ).fetchall()

    pairs: set[tuple[str, str]] = set()
    for r in rows:
        src = r["source_qualified"]
        tgt = _resolve_import_target(
            r["target_qualified"], r["file_path"], module_map, set(instability)
        )
        if src != tgt and src in instability and tgt in instability:
            if src not in facades and tgt not in facades:
                pairs.add((src, tgt))

    return [
        SdpViolation(src, tgt, instability[src], instability[tgt])
        for src, tgt in sorted(pairs)
        if instability[tgt] > instability[src] + margin
    ]


def god_modules(
    store: GraphStore, percentile: float = 90, min_ca: float = 0
) -> list[ModuleMetrics]:
    """Detect god modules: statistical outliers of fan-in (Ca).

    A module is a "god" if its Ca exceeds the project's ``percentile``
    percentile **and** reaches the absolute minimum ``min_ca``. The
    percentile alone would always flag the top 10%, even in a healthy
    project; the absolute minimum avoids flagging modules with little fan-in.

    Requires at least 2 modules for the computation to make sense;
    with fewer modules it always returns an empty list.

    Args:
        store: GraphStore with the project index.
        percentile: Ca percentile used as the threshold (default 90).
        min_ca: Minimum Ca (inclusive) to be a god module. 0 disables the
            filter; the CLI passes the value of ``god_module_min_ca``.

    Returns:
        List of :class:`ModuleMetrics` whose fan-in exceeds the threshold.
        Empty list if there are no outliers or the index has < 2 modules.
    """
    if not (1 <= percentile <= 99):
        raise ValueError(f"percentile must be in [1, 99], got {percentile}")

    metrics = compute_metrics(store)
    if len(metrics) < 2:
        return []

    fan_ins = [m.fan_in for m in metrics]
    threshold = percentile_threshold(fan_ins, percentile)

    # Only those strictly above the threshold are outliers
    return [m for m in metrics if m.fan_in > threshold and m.fan_in >= min_ca]
