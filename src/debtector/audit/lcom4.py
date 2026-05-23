"""LCOM4 (Lack of Cohesion of Methods, v4) for the audit surface.

LCOM4 measures internal class cohesion by counting connected components in the
undirected graph whose nodes are the methods of the class and whose edges are
``CALLS`` edges between two methods of the same class.

Reading:
    - ``1``  → cohesive class, single internal cluster.
    - ``>1`` → candidate to split (independent responsibilities).
    - ``0``  → class has no methods (no signal to report).
"""

from __future__ import annotations

import networkx as nx

from ..graph_store import GraphStore
from ..models import EdgeKind


def compute_lcom4(store: GraphStore, class_qualified_name: str) -> int:
    """Compute LCOM4 for a single class.

    Args:
        store: ``GraphStore`` holding the indexed project.
        class_qualified_name: Qualified name of the class (e.g.
            ``"src/auth/service.py::AuthService"``).

    Returns:
        Number of connected components among the class methods. ``0`` when the
        class has no methods.
    """
    methods = {
        e.target_qualified
        for e in store.get_outgoing(class_qualified_name, edge_kind=EdgeKind.HAS_METHOD)
    }
    if not methods:
        return 0

    graph: nx.Graph = nx.Graph()
    graph.add_nodes_from(methods)
    for method in methods:
        for edge in store.get_outgoing(method, edge_kind=EdgeKind.CALLS):
            if edge.target_qualified in methods:
                graph.add_edge(method, edge.target_qualified)

    return nx.number_connected_components(graph)
