"""Utilidades compartidas de Debtector.

Funciones auxiliares sin dependencias internas que pueden importarse
desde parsers, GraphStore y CLI sin riesgo de ciclos de importación.
"""

from __future__ import annotations

from pathlib import Path


def is_test_file(file_path: str) -> bool:
    """Return ``True`` if *file_path* points to a test file.

    Detection is based on the file name alone (no disk access):

    - Python: ``test_*.py`` prefix or ``*_test.py`` suffix.
    - JavaScript/TypeScript: ``*.test.js``, ``*.test.ts``,
      ``*.spec.js``, ``*.spec.ts``.

    Args:
        file_path: Absolute or relative path to the file.

    Returns:
        ``True`` when the file is recognised as a test file.
    """
    name = Path(file_path).name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".test.js")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.js")
    )
