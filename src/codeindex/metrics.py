"""
Módulo de métricas de acoplamiento para CodeIndex.

Calcula métricas estructurales a nivel de módulo (archivo):

- Fan-in  (Ca): número de módulos que importan este módulo.
- Fan-out (Ce): número de módulos que este módulo importa.
- Inestabilidad (I = Ce / (Ca + Ce)): 0 = muy estable, 1 = muy inestable.
- Ciclos: componentes fuertemente conectados de tamaño > 1 sobre
  aristas IMPORTS_FROM y CALLS.

Las métricas se calculan sobre aristas IMPORTS_FROM del grafo.
Los imports a paquetes externos (sin nodo File en el índice) también
contribuyen al fan-out del módulo importador.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .graph_store import GraphStore
from .models import EdgeKind, NodeKind

# Tipos de aristas que se consideran para la detección de ciclos
_CYCLE_EDGE_KINDS = (EdgeKind.IMPORTS_FROM, EdgeKind.CALLS)


@dataclass
class ModuleMetrics:
    """Métricas de acoplamiento para un único módulo (archivo).

    Args:
        file_path: Ruta relativa del archivo.
        fan_in: Fan-in (Ca) — número de aristas IMPORTS_FROM entrantes.
        fan_out: Fan-out (Ce) — número de aristas IMPORTS_FROM salientes.
        instability: I = Ce / (Ca + Ce). 0.0 si el módulo está aislado.
    """

    file_path: str
    fan_in: int
    fan_out: int
    instability: float


def compute_metrics(store: GraphStore) -> list[ModuleMetrics]:
    """Calcula Ca, Ce e I para todos los módulos indexados.

    Solo los nodos de tipo ``File`` participan como unidades de análisis.
    Los imports a paquetes externos (e.g. ``"flask"``) incrementan el Ce
    del importador aunque no tengan nodo propio en el índice.

    Usa tres consultas SQL agregadas para evitar N queries por archivo.

    Args:
        store: GraphStore con el índice del proyecto.

    Returns:
        Lista de :class:`ModuleMetrics`, una entrada por archivo indexado.
        Lista vacía si el índice está vacío.
    """
    conn = store._conn

    # Obtener todos los nodos File
    file_rows = conn.execute(
        "SELECT qualified_name FROM nodes WHERE kind = ?",
        (NodeKind.FILE,),
    ).fetchall()

    if not file_rows:
        return []

    # Ce por archivo: conteo de aristas IMPORTS_FROM salientes
    ce_rows = conn.execute(
        "SELECT source_qualified, COUNT(*) AS cnt FROM edges"
        " WHERE kind = ? GROUP BY source_qualified",
        (EdgeKind.IMPORTS_FROM,),
    ).fetchall()
    ce_map: dict[str, int] = {r["source_qualified"]: r["cnt"] for r in ce_rows}

    # Ca por archivo: conteo de aristas IMPORTS_FROM entrantes
    ca_rows = conn.execute(
        "SELECT target_qualified, COUNT(*) AS cnt FROM edges"
        " WHERE kind = ? GROUP BY target_qualified",
        (EdgeKind.IMPORTS_FROM,),
    ).fetchall()
    ca_map: dict[str, int] = {r["target_qualified"]: r["cnt"] for r in ca_rows}

    results: list[ModuleMetrics] = []
    for row in file_rows:
        qn: str = row["qualified_name"]
        ce = ce_map.get(qn, 0)
        ca = ca_map.get(qn, 0)
        total = ca + ce
        instability = ce / total if total > 0 else 0.0
        results.append(
            ModuleMetrics(
                file_path=qn,  # para File nodes, qualified_name == file_path
                fan_in=ca,
                fan_out=ce,
                instability=instability,
            )
        )

    return results


def find_cycles(store: GraphStore) -> list[list[str]]:
    """Detecta ciclos en el grafo usando el algoritmo de Tarjan (SCCs).

    Considera aristas de tipo ``IMPORTS_FROM`` y ``CALLS``. Solo incluye
    nodos que existen como ``File`` en el índice; los targets externos
    (paquetes de terceros sin nodo propio) se ignoran.

    Args:
        store: GraphStore con el índice del proyecto.

    Returns:
        Lista de ciclos. Cada ciclo es una lista de ``qualified_name``
        de los nodos que forman la componente fuertemente conectada.
        Lista vacía si no hay ciclos.
    """
    conn = store._conn

    # Conjunto de nodos File indexados (los externos se descartan)
    file_set: set[str] = {
        r["qualified_name"]
        for r in conn.execute(
            "SELECT qualified_name FROM nodes WHERE kind = ?", (NodeKind.FILE,)
        ).fetchall()
    }

    if not file_set:
        return []

    # Construir lista de adyacencia solo con nodos indexados
    placeholders = ",".join("?" * len(_CYCLE_EDGE_KINDS))
    rows = conn.execute(
        f"SELECT source_qualified, target_qualified FROM edges"  # nosec B608
        f" WHERE kind IN ({placeholders})",
        list(_CYCLE_EDGE_KINDS),
    ).fetchall()

    adj: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        src, tgt = r["source_qualified"], r["target_qualified"]
        if src in file_set and tgt in file_set:
            adj[src].append(tgt)

    # Algoritmo de Tarjan para componentes fuertemente conectadas (SCCs)
    index_counter = [0]
    stack: list[str] = []
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[list[str]] = []

    def strongconnect(node: str) -> None:
        index[node] = index_counter[0]
        lowlink[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack[node] = True

        for neighbor in adj.get(node, []):
            if neighbor not in index:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif on_stack.get(neighbor, False):
                lowlink[node] = min(lowlink[node], index[neighbor])

        if lowlink[node] == index[node]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == node:
                    break
            if len(scc) > 1:
                sccs.append(scc)

    for node in file_set:
        if node not in index:
            strongconnect(node)

    return sccs
