"""
Generación de embeddings para búsqueda semántica.

Usa fastembed (ONNX Runtime, sin PyTorch) con el modelo BAAI/bge-small-en-v1.5.
El modelo se descarga una sola vez y se cachea en ~/.cache/fastembed/.

Uso:
    from codeindex.embedder import embed_text, embed_texts, node_to_text

    vec = embed_text("authentication middleware")
    vecs = embed_texts(["auth service", "payment gateway"])
"""

from __future__ import annotations

import struct

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_EMBEDDING_DIM = 384

# Singleton del modelo (lazy init al primer uso)
_model = None


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
                "fastembed no está instalado. Instálalo con: uv add 'codeindex[search]'"
            ) from exc
        _model = TextEmbedding(_MODEL_NAME)
    return _model


def node_to_text(node) -> str:
    """Convierte un nodo (NodeInfo o GraphNode) a texto para embebido.

    El texto combina kind, nombre, signatura y docstring —los campos con
    más información semántica sobre el símbolo.

    Args:
        node: Instancia de :class:`~codeindex.models.NodeInfo` o
            :class:`~codeindex.models.GraphNode`.

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
