"""Tests for cycle prioritization in the audit surface.

Gherkin contract:

    Given dos ciclos detectados, ciclo1 con max fan-in=10 y ciclo2 con max fan-in=3
    When se priorizan los ciclos
    Then ciclo1 aparece primero en la lista ordenada

    Given un grafo sin ciclos
    When se ejecuta la priorización
    Then se devuelve lista vacía sin error
"""

from __future__ import annotations

from debtector.audit.cycle_priority import PrioritizedCycle, prioritize_cycles
from debtector.graph_store import GraphStore
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


def _file(path: str) -> NodeInfo:
    return NodeInfo(
        kind=NodeKind.FILE,
        name=path.split("/")[-1],
        qualified_name=path,
        file_path=path,
        language="python",
    )


def _imports(source: str, target: str) -> EdgeInfo:
    return EdgeInfo(
        kind=EdgeKind.IMPORTS_FROM,
        source=source,
        target=target,
        file_path=source,
        line=1,
    )


def _make_cycle(store: GraphStore, members: list[str], extra_importers: dict[str, int]) -> None:
    """Build a cycle through ``members`` plus N dangling importers per member.

    ``extra_importers[node]`` adds N extra files importing ``node`` to inflate
    its fan-in beyond the +1 already contributed by the cycle predecessor.
    """
    for m in members:
        store.store_file(m, [_file(m)], [])

    for i, src in enumerate(members):
        tgt = members[(i + 1) % len(members)]
        store.store_file(src, [_file(src)], [_imports(src, tgt)])

    for node, count in extra_importers.items():
        for i in range(count):
            extra_path = f"extra/{node.replace('/', '_')}_imp_{i}.py"
            store.store_file(extra_path, [_file(extra_path)], [_imports(extra_path, node)])


class TestPrioritizeCycles:
    """Unit tests for prioritize_cycles()."""

    def test_empty_graph_returns_empty_list(self, tmp_db: GraphStore) -> None:
        """Given un grafo sin ciclos: lista vacía sin error."""
        assert prioritize_cycles(tmp_db) == []

    def test_graph_without_cycles_returns_empty(self, tmp_db: GraphStore) -> None:
        """A DAG (no cycle) yields no prioritized cycles."""
        tmp_db.store_file("src/a.py", [_file("src/a.py")], [_imports("src/a.py", "src/b.py")])
        tmp_db.store_file("src/b.py", [_file("src/b.py")], [])

        assert prioritize_cycles(tmp_db) == []

    def test_cycle_with_higher_fanin_comes_first(self, tmp_db: GraphStore) -> None:
        """Cycle whose most-exposed node has the highest fan-in ranks first."""
        # Cycle 1: a → b → a. Inflate `a` so its fan-in is 10 (9 extras + 1 from b).
        _make_cycle(tmp_db, ["src/a.py", "src/b.py"], {"src/a.py": 9})
        # Cycle 2: c → d → c. Inflate `c` so its fan-in is 3 (2 extras + 1 from d).
        _make_cycle(tmp_db, ["src/c.py", "src/d.py"], {"src/c.py": 2})

        result = prioritize_cycles(tmp_db)

        assert len(result) == 2
        assert isinstance(result[0], PrioritizedCycle)
        assert result[0].max_fan_in == 10
        assert result[1].max_fan_in == 3
        # The cycle whose max-fan-in node is `src/a.py` must come first.
        assert "src/a.py" in result[0].cycle
        assert "src/c.py" in result[1].cycle

    def test_result_is_descending_by_max_fanin(self, tmp_db: GraphStore) -> None:
        """Returned list is ordered by max_fan_in descending."""
        _make_cycle(tmp_db, ["src/a.py", "src/b.py"], {"src/a.py": 9})
        _make_cycle(tmp_db, ["src/c.py", "src/d.py"], {"src/c.py": 2})

        result = prioritize_cycles(tmp_db)

        fan_ins = [c.max_fan_in for c in result]
        assert fan_ins == sorted(fan_ins, reverse=True)
