"""
Módulo de métricas de acoplamiento para CodeIndex.

Calcula métricas estructurales a nivel de módulo (archivo):

- Fan-in  (Ca): número de módulos que importan este módulo.
- Fan-out (Ce): número de módulos que este módulo importa.
- Inestabilidad (I = Ce / (Ca + Ce)): 0 = muy estable, 1 = muy inestable.

Las métricas se calculan sobre aristas IMPORTS_FROM del grafo.
Los imports a paquetes externos (sin nodo File en el índice) también
contribuyen al fan-out del módulo importador.
"""

from __future__ import annotations

from dataclasses import dataclass

from .graph_store import GraphStore
from .models import EdgeKind, NodeKind


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
