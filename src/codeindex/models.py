"""
Modelos de datos para CodeIndex.

Diseño inspirado en graph stores reales: cada símbolo es un NODO con un
qualified_name único, y las relaciones (imports, herencia, llamadas) son
ARISTAS dirigidas entre nodos.

El qualified_name es la "dirección completa" de cada símbolo:
    archivo.py                          → El archivo en sí
    archivo.py::MiClase                 → Una clase
    archivo.py::MiClase.mi_metodo       → Un método
    archivo.py::mi_funcion              → Una función top-level
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# ──────────────────────────────────────────────
# Tipos de nodos y aristas
# ──────────────────────────────────────────────


class NodeKind(str, Enum):
    """Tipos de nodos en el grafo de código."""

    FILE = "File"
    CLASS = "Class"
    FUNCTION = "Function"
    METHOD = "Method"


class EdgeKind(str, Enum):
    """Tipos de relaciones entre nodos."""

    CONTAINS = "CONTAINS"  # archivo contiene clase/función
    HAS_METHOD = "HAS_METHOD"  # clase contiene método
    IMPORTS_FROM = "IMPORTS_FROM"  # archivo importa de módulo
    CALLS = "CALLS"  # función/método llama a otra
    INHERITS = "INHERITS"  # clase hereda de otra
    DEPENDS_ON = "DEPENDS_ON"  # dependencia genérica
    COVERS = "COVERS"  # función/método de test ejerce a símbolo de producción


# ──────────────────────────────────────────────
# Nodos
# ──────────────────────────────────────────────


@dataclass
class NodeInfo:
    """
    Información de un nodo para insertar en el grafo.

    Es lo que un parser produce. El GraphStore lo convierte en un
    registro persistente con ID y timestamps.

    Args:
        kind: Tipo de nodo (File, Class, Function, Method)
        name: Nombre corto ("get_user", "UserService")
        qualified_name: Nombre completo único ("src/app.py::UserService.get_user")
        file_path: Ruta del archivo donde vive
        line_start: Línea de inicio
        line_end: Línea de fin
        language: Lenguaje de programación
        parent_name: Nombre de la clase padre (para métodos)
        signature: Firma completa ("def get_user(self, id: int) -> User")
        docstring: Documentación del símbolo
        decorators: Lista de decoradores
        extra: Datos adicionales en formato libre
    """

    kind: str
    name: str
    qualified_name: str
    file_path: str
    line_start: int = 0
    line_end: int = 0
    language: str = ""
    parent_name: str | None = None
    signature: str | None = None
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class EdgeInfo:
    """
    Información de una arista para insertar en el grafo.

    Conecta dos nodos por sus qualified_names.

    Args:
        kind: Tipo de relación (CONTAINS, IMPORTS_FROM, CALLS, etc.)
        source: qualified_name del nodo origen
        target: qualified_name del nodo destino
        file_path: Archivo donde se establece la relación
        line: Línea donde ocurre (ej: línea del import o la llamada)
        extra: Datos adicionales
    """

    kind: str
    source: str
    target: str
    file_path: str
    line: int = 0
    extra: dict = field(default_factory=dict)


# ──────────────────────────────────────────────
# Resultados de consultas (lo que devuelve el GraphStore)
# ──────────────────────────────────────────────


@dataclass
class GraphNode:
    """Nodo almacenado en el grafo (con ID y metadatos del store)."""

    id: int
    kind: str
    name: str
    qualified_name: str
    file_path: str
    line_start: int
    line_end: int
    language: str
    parent_name: str | None
    signature: str | None
    docstring: str | None
    file_hash: str | None
    extra: dict


@dataclass
class GraphEdge:
    """Arista almacenada en el grafo."""

    id: int
    kind: str
    source_qualified: str
    target_qualified: str
    file_path: str
    line: int
    extra: dict


@dataclass
class GraphStats:
    """Estadísticas agregadas del grafo."""

    total_nodes: int
    total_edges: int
    nodes_by_kind: dict[str, int]
    edges_by_kind: dict[str, int]
    languages: list[str]
    files_count: int
    embeddings_count: int = 0


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def make_qualified_name(
    file_path: str,
    name: str,
    kind: str,
    parent_name: str | None = None,
) -> str:
    """
    Construye el qualified_name de un símbolo.

    Ejemplos:
        make_qualified_name("src/app.py", "app.py", "File")
            → "src/app.py"
        make_qualified_name("src/app.py", "UserService", "Class")
            → "src/app.py::UserService"
        make_qualified_name("src/app.py", "get_user", "Method", "UserService")
            → "src/app.py::UserService.get_user"
        make_qualified_name("src/app.py", "create_app", "Function")
            → "src/app.py::create_app"
    """
    if kind == NodeKind.FILE:
        return file_path
    if parent_name:
        return f"{file_path}::{parent_name}.{name}"
    return f"{file_path}::{name}"


def node_to_dict(n: GraphNode) -> dict:
    """Convierte un GraphNode a diccionario (para serialización/API)."""
    return {
        "id": n.id,
        "kind": n.kind,
        "name": n.name,
        "qualified_name": n.qualified_name,
        "file_path": n.file_path,
        "line_start": n.line_start,
        "line_end": n.line_end,
        "language": n.language,
        "parent_name": n.parent_name,
        "signature": n.signature,
    }


def edge_to_dict(e: GraphEdge) -> dict:
    """Convierte un GraphEdge a diccionario."""
    return {
        "id": e.id,
        "kind": e.kind,
        "source": e.source_qualified,
        "target": e.target_qualified,
        "file_path": e.file_path,
        "line": e.line,
    }
