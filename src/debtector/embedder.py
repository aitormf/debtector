"""
Generación de embeddings para búsqueda semántica.

Usa fastembed (ONNX Runtime, sin PyTorch) con el modelo BAAI/bge-small-en-v1.5.
El modelo se descarga una sola vez y se cachea en ~/.cache/fastembed/.

Uso:
    from debtector.embedder import embed_text, embed_texts, build_rich_node_text

    vec = embed_text("authentication middleware")
    vecs = embed_texts(["auth service", "payment gateway"])
"""

from __future__ import annotations

import re
import struct

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_EMBEDDING_DIM = 384

# Singleton del modelo (lazy init al primer uso)
_model = None

# Tokens de ruta sin valor semántico que se filtran al normalizar file_path
_PATH_SKIP = {"src", "lib", "app", "index", "__init__", "py", "js", "ts", "tsx", "jsx", "vue"}


def _get_model():
    """Devuelve el modelo de embeddings, inicializándolo al primer uso.

    Returns:
        Instancia de ``fastembed.TextEmbedding`` lista para usar.

    Raises:
        ImportError: Si fastembed no está instalado.
    """
    global _model
    if _model is None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise ImportError(
                "fastembed no está instalado. Instálalo con: uv add 'debtector[search]'"
            ) from exc
        _model = TextEmbedding(_MODEL_NAME)
    return _model


def path_to_tokens(file_path: str) -> list[str]:
    """Divide una ruta de archivo en tokens semánticos.

    Separa por ``/``, ``.`` y ``_``, filtrando extensiones y directorios
    estructurales sin valor semántico (``src``, ``lib``, ``index``, etc.).

    Args:
        file_path: Ruta relativa del archivo (p.ej. ``src/auth/service.py``).

    Returns:
        Lista de tokens (p.ej. ``["auth", "service"]``).
    """
    tokens = re.split(r"[/._]", file_path)
    return [t for t in tokens if t and t not in _PATH_SKIP]


def build_rich_node_text(
    *,
    kind: str,
    name: str,
    signature: str | None = None,
    docstring: str | None = None,
    path_tokens: list[str] | None = None,
    import_names: list[str] | None = None,
    child_names: list[str] | None = None,
    test_names: list[str] | None = None,
) -> str:
    """Construye texto enriquecido de un nodo para su embedding.

    Combina la información estructural del nodo (kind, nombre, firma, docstring)
    con contexto derivado del índice: tokens de la ruta del archivo, módulos
    importados, símbolos hijos y archivos de test que lo ejercen.

    Args:
        kind: Tipo de nodo (``"File"``, ``"Class"``, ``"Function"``, ``"Method"``).
        name: Nombre corto del símbolo.
        signature: Firma de la función/método, si existe.
        docstring: Docstring del símbolo, si existe.
        path_tokens: Tokens semánticos de la ruta del archivo contenedor.
        import_names: Nombres de módulos importados por el archivo contenedor.
        child_names: Nombres de símbolos hijos: métodos para clases,
            clases/funciones para archivos.
        test_names: Stems de archivos de test que referencian este nodo.

    Returns:
        Cadena de texto lista para pasar a un modelo de embeddings.
    """
    parts: list[str] = []

    # 1. Tipo + nombre
    parts.append(kind)
    parts.append(name)

    # 2. Ruta del archivo como contexto de dominio
    if path_tokens:
        parts.append("path " + " ".join(path_tokens))

    # 3. Firma y docstring
    if signature:
        parts.append(signature)
    if docstring:
        parts.append(docstring)

    # 4. Contexto estructural: imports y símbolos hijos
    if import_names:
        parts.append("imports " + " ".join(import_names))
    if child_names:
        parts.append(" ".join(child_names))

    # 5. Cobertura de tests
    if test_names:
        parts.append("tested by " + " ".join(test_names))

    return " ".join(parts).strip()


def node_to_text(node) -> str:
    """Convierte un nodo (NodeInfo o GraphNode) a texto para embebido.

    Versión simple sin contexto adicional de la DB. Útil para embeber
    la query en ``semantic_search``.

    Args:
        node: Instancia de :class:`~debtector.models.NodeInfo` o
            :class:`~debtector.models.GraphNode`.

    Returns:
        Cadena de texto normalizada lista para pasar a un modelo de embeddings.
    """
    parts = [str(node.kind), node.name]
    if getattr(node, "signature", None):
        parts.append(node.signature)
    if getattr(node, "docstring", None):
        parts.append(node.docstring)
    return " ".join(parts).strip()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Genera embeddings para una lista de textos.

    Args:
        texts: Lista de cadenas a embebir. No debe estar vacía.

    Returns:
        Lista de vectores float (uno por texto), cada uno de dimensión 384.

    Raises:
        ImportError: Si fastembed no está instalado.
    """
    model = _get_model()
    return [list(vec) for vec in model.embed(texts)]


def embed_text(text: str) -> list[float]:
    """Genera el embedding de un único texto.

    Args:
        text: Cadena a embebir.

    Returns:
        Vector de 384 floats.

    Raises:
        ImportError: Si fastembed no está instalado.
    """
    return embed_texts([text])[0]


def serialize_f32(vector: list[float]) -> bytes:
    """Serializa un vector float32 a bytes para almacenamiento en sqlite-vec.

    Args:
        vector: Lista de valores float.

    Returns:
        Bytes en formato little-endian float32 (4 bytes por elemento).
    """
    return struct.pack(f"{len(vector)}f", *vector)
