"""
Módulo de métricas de acoplamiento para CodeIndex.

Calcula métricas estructurales a nivel de módulo (archivo):

- Fan-in  (Ca): número de módulos que importan este módulo.
- Fan-out (Ce): número de módulos que este módulo importa.
- Inestabilidad (I = Ce / (Ca + Ce)): 0 = muy estable, 1 = muy inestable.
- Ciclos: componentes fuertemente conectados de tamaño > 1 sobre
  aristas IMPORTS_FROM y CALLS.
- God modules: outliers estadísticos de Ca por encima del percentil 90
  del proyecto (umbral relativo, no absoluto).

Las métricas se calculan sobre aristas IMPORTS_FROM del grafo.
Los imports a paquetes externos (sin nodo File en el índice) también
contribuyen al fan-out del módulo importador.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass

from .graph_store import GraphStore
from .models import EdgeKind, NodeKind

# Tipos de aristas que se consideran para la detección de ciclos
_CYCLE_EDGE_KINDS = (EdgeKind.IMPORTS_FROM, EdgeKind.CALLS)

# Peso de las aristas USES_TYPE en el cálculo de Ca/Ce.
# Menor que IMPORTS_FROM (peso 1.0) porque una referencia de tipo en
# una firma es un acoplamiento más débil que un import explícito.
USES_TYPE_WEIGHT: float = 0.5


@dataclass
class ModuleMetrics:
    """Métricas de acoplamiento para un único módulo (archivo).

    Args:
        file_path: Ruta relativa del archivo.
        fan_in: Fan-in (Ca) — suma ponderada de aristas entrantes. Las aristas
            IMPORTS_FROM cuentan 1.0; las USES_TYPE cuentan ``USES_TYPE_WEIGHT``.
        fan_out: Fan-out (Ce) — suma ponderada de aristas salientes. Mismo
            esquema de pesos que ``fan_in``.
        instability: I = Ce / (Ca + Ce). 0.0 si el módulo está aislado.
    """

    file_path: str
    fan_in: float
    fan_out: float
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

    # Ce por archivo: aristas IMPORTS_FROM salientes (peso 1.0)
    ce_rows = conn.execute(
        "SELECT source_qualified, COUNT(*) AS cnt FROM edges"
        " WHERE kind = ? GROUP BY source_qualified",
        (EdgeKind.IMPORTS_FROM,),
    ).fetchall()
    ce_map: dict[str, float] = {r["source_qualified"]: float(r["cnt"]) for r in ce_rows}

    # Ce adicional: aristas USES_TYPE salientes (peso USES_TYPE_WEIGHT)
    ut_ce_rows = conn.execute(
        "SELECT source_qualified, COUNT(*) AS cnt FROM edges"
        " WHERE kind = ? GROUP BY source_qualified",
        (EdgeKind.USES_TYPE,),
    ).fetchall()
    for r in ut_ce_rows:
        ce_map[r["source_qualified"]] = (
            ce_map.get(r["source_qualified"], 0.0) + r["cnt"] * USES_TYPE_WEIGHT
        )

    # Ca por archivo: aristas IMPORTS_FROM entrantes (peso 1.0)
    ca_rows = conn.execute(
        "SELECT target_qualified, COUNT(*) AS cnt FROM edges"
        " WHERE kind = ? GROUP BY target_qualified",
        (EdgeKind.IMPORTS_FROM,),
    ).fetchall()
    ca_map: dict[str, float] = {r["target_qualified"]: float(r["cnt"]) for r in ca_rows}

    # Ca adicional: aristas USES_TYPE entrantes (peso USES_TYPE_WEIGHT).
    # Solo cuentan si el target es un nodo File indexado (resolución interna).
    ut_ca_rows = conn.execute(
        "SELECT target_qualified, COUNT(*) AS cnt FROM edges"
        " WHERE kind = ? GROUP BY target_qualified",
        (EdgeKind.USES_TYPE,),
    ).fetchall()
    for r in ut_ca_rows:
        ca_map[r["target_qualified"]] = (
            ca_map.get(r["target_qualified"], 0.0) + r["cnt"] * USES_TYPE_WEIGHT
        )

    results: list[ModuleMetrics] = []
    for row in file_rows:
        qn: str = row["qualified_name"]
        ce = ce_map.get(qn, 0.0)
        ca = ca_map.get(qn, 0.0)
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

    # Algoritmo de Tarjan iterativo para componentes fuertemente conectadas.
    # Se usa la versión iterativa explícita (worklist) en lugar de la recursiva
    # para evitar RecursionError en grafos con cadenas de dependencias largas.
    #
    # Estado del iterador por nodo: índice en adj[node] del próximo vecino
    # que aún hay que procesar. Cuando se agotan los vecinos se hace el check
    # SCC del nodo igual que en la versión recursiva.
    index_counter = [0]
    scc_stack: list[str] = []  # pila de Tarjan
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[list[str]] = []

    # worklist: (nodo, iterador-de-vecinos). Simula el call-stack de la versión
    # recursiva sin consumir stack frames de Python.
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
                # Avanzar al siguiente vecino sin sacar el frame
                worklist[-1] = (node, nei_idx + 1)
                neighbor = neighbors[nei_idx]

                if neighbor not in index:
                    # Descubrir vecino: "llamada recursiva"
                    index[neighbor] = index_counter[0]
                    lowlink[neighbor] = index_counter[0]
                    index_counter[0] += 1
                    scc_stack.append(neighbor)
                    on_stack[neighbor] = True
                    worklist.append((neighbor, 0))
                elif on_stack.get(neighbor, False):
                    lowlink[node] = min(lowlink[node], index[neighbor])
            else:
                # Todos los vecinos procesados: "retorno de llamada recursiva"
                worklist.pop()
                if worklist:
                    parent = worklist[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])

                # Detectar raíz de SCC
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
    """Métricas de herencia para una clase.

    Args:
        qualified_name: Identificador único de la clase.
        depth: Profundidad en la jerarquía de herencia (0 = clase raíz).
        children: Número de clases que heredan directamente de esta.
    """

    qualified_name: str
    depth: int
    children: int


def inheritance_metrics(store: GraphStore) -> list[InheritanceMetrics]:
    """Calcula profundidad de herencia y número de hijos para cada clase.

    Recorre las aristas ``INHERITS`` del grafo. La profundidad se calcula
    como el camino más largo desde la raíz de la jerarquía hasta la clase.
    Los ciclos de herencia (inválidos en Python/JS) se cortan al detectar
    nodos ya visitados.

    Args:
        store: GraphStore con el índice del proyecto.

    Returns:
        Lista de :class:`InheritanceMetrics`, una por clase indexada.
        Lista vacía si no hay clases en el índice.
    """
    conn = store._conn

    # Obtener todos los nodos Class y Method con kind=Class
    class_rows = conn.execute(
        "SELECT qualified_name FROM nodes WHERE kind = ?",
        (NodeKind.CLASS,),
    ).fetchall()

    if not class_rows:
        return []

    class_set: set[str] = {r["qualified_name"] for r in class_rows}

    # Aristas INHERITS: source=hijo, target=padre
    edge_rows = conn.execute(
        "SELECT source_qualified, target_qualified FROM edges WHERE kind = ?",
        (EdgeKind.INHERITS,),
    ).fetchall()

    # children_map[parent] = número de hijos directos
    children_map: dict[str, int] = defaultdict(int)
    # parent_map[child] = qualified_name del padre (puede ser externo)
    parent_map: dict[str, str] = {}

    for r in edge_rows:
        child, parent = r["source_qualified"], r["target_qualified"]
        parent_map[child] = parent
        if parent in class_set:
            children_map[parent] += 1

    def _depth(qn: str, visited: set[str]) -> int:
        """Calcula la profundidad recursivamente, cortando ciclos."""
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


def god_modules(store: GraphStore, percentile: float = 90) -> list[ModuleMetrics]:
    """Detecta módulos dios: outliers estadísticos de fan-in (Ca).

    Un módulo es "dios" si su Ca supera el percentil ``percentile`` del
    proyecto. El umbral es relativo al proyecto, no absoluto, para
    adaptarse a bases de código de cualquier tamaño.

    Requiere al menos 2 módulos para que el cálculo tenga sentido;
    con menos módulos devuelve siempre una lista vacía.

    Args:
        store: GraphStore con el índice del proyecto.
        percentile: Percentil de Ca usado como umbral (por defecto 90).

    Returns:
        Lista de :class:`ModuleMetrics` cuyos fan-in superan el umbral.
        Lista vacía si no hay outliers o el índice tiene < 2 módulos.
    """
    if not (1 <= percentile <= 99):
        raise ValueError(f"percentile must be in [1, 99], got {percentile}")

    metrics = compute_metrics(store)
    if len(metrics) < 2:
        return []

    fan_ins = [m.fan_in for m in metrics]
    threshold = statistics.quantiles(fan_ins, n=100)[int(percentile) - 1]

    # Solo son outliers los que estén estrictamente por encima del umbral
    return [m for m in metrics if m.fan_in > threshold]
