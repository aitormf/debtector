"""Function-level complexity findings for the audit health score (D-0006).

Each production function or method whose cyclomatic complexity reaches a
threshold is a finding: ``high`` from ``complexity_high``, ``medium`` from
``complexity_medium``. Test-file functions never count. Nested functions have
no node of their own, so they only count through their enclosing function.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..models import GraphNode

#: Default ``complexity_medium`` / ``complexity_high``: radon grades D and E.
DEFAULT_COMPLEXITY_MEDIUM: int = 21
DEFAULT_COMPLEXITY_HIGH: int = 31


@dataclass(frozen=True)
class ComplexityFinding:
    """A function or method too complex to read comfortably.

    Args:
        qualified_name: Id of the function or method.
        file_path: Relative path of its file.
        line: First line of the function.
        complexity: Cyclomatic complexity of the function.
        severity: ``"high"`` or ``"medium"``.
    """

    qualified_name: str
    file_path: str
    line: int
    complexity: int
    severity: str


def select_complexity_findings(
    nodes: Iterable[GraphNode],
    *,
    medium: float,
    high: float,
    is_test: Callable[[str], bool],
) -> list[ComplexityFinding]:
    """Pick the production functions whose complexity reaches a threshold.

    Args:
        nodes: Function and Method nodes carrying ``extra["complexity"]``.
        medium: Complexity from which a function is a ``medium`` finding.
        high: Complexity from which a function is a ``high`` finding.
        is_test: Predicate on a node's file path; test files are skipped, as are
            external nodes (``../`` paths, test directories outside the index).

    Returns:
        The findings, most complex first.
    """
    findings = []
    for node in nodes:
        complexity = int(node.extra.get("complexity", 0))
        if complexity < medium or node.file_path.startswith("../") or is_test(node.file_path):
            continue
        findings.append(
            ComplexityFinding(
                qualified_name=node.qualified_name,
                file_path=node.file_path,
                line=node.line_start,
                complexity=complexity,
                severity="high" if complexity >= high else "medium",
            )
        )
    return sorted(findings, key=lambda f: (-f.complexity, f.qualified_name))
