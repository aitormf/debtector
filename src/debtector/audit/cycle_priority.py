"""Cycle prioritization for the audit surface.

Cycles are detected by :func:`debtector.metrics.find_cycles` (Tarjan SCCs over
``IMPORTS_FROM`` and ``CALLS``). For an auditor, the raw list is not enough:
a cycle that traps a high-fan-in module is far more urgent to break than a
cycle between two leaf modules.

The heuristic adopted here ranks each cycle by the **fan-in (Ca) of its most
exposed node** — i.e. ``max(fan_in[n] for n in cycle)``. Breaking that cycle
unblocks the largest blast radius first. This is the "qué ciclo romper primero"
question stated in the Phase 3 audit spec.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..graph_store import GraphStore
from ..metrics import compute_metrics, find_cycles


@dataclass(frozen=True)
class PrioritizedCycle:
    """A detected cycle paired with the prioritization signal.

    Args:
        cycle: Qualified names of the nodes in the strongly connected component.
        max_fan_in: Maximum fan-in (Ca) across ``cycle``. Higher = break first.
        pivot: Node within the cycle that has the highest fan-in (Ca).
    """

    cycle: list[str]
    max_fan_in: float
    pivot: str = ""


def prioritize_cycles(store: GraphStore) -> list[PrioritizedCycle]:
    """Rank detected cycles by the fan-in of their most exposed node.

    Args:
        store: ``GraphStore`` holding the indexed project.

    Returns:
        Cycles ordered by ``max_fan_in`` descending. Empty list if no cycles
        exist (including the empty-graph case) — never raises.
    """
    cycles = find_cycles(store)
    if not cycles:
        return []

    fan_in_by_file: dict[str, float] = {m.file_path: m.fan_in for m in compute_metrics(store)}

    ranked: list[PrioritizedCycle] = []
    for cycle in cycles:
        fan_ins = [(n, fan_in_by_file.get(n, 0.0)) for n in cycle]
        max_fan_in = max((f for _, f in fan_ins), default=0.0)
        pivot = max(fan_ins, key=lambda x: x[1])[0] if fan_ins else ""
        ranked.append(PrioritizedCycle(cycle=cycle, max_fan_in=max_fan_in, pivot=pivot))
    ranked.sort(key=lambda c: c.max_fan_in, reverse=True)
    return ranked
