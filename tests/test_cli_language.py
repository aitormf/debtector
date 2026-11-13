"""Guard: user-facing output and source text must be in English, not Spanish."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "debtector"
SPANISH_CHARS = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡]")


def test_source_has_no_spanish_characters() -> None:
    """No file under src/debtector contains Spanish-specific characters."""
    offenders = [
        f"{path.relative_to(SRC)}:{lineno}"
        for path in sorted(SRC.rglob("*.py"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if SPANISH_CHARS.search(line)
    ]
    assert not offenders, f"Spanish characters found at: {offenders[:20]}"


def test_cli_has_no_common_spanish_words() -> None:
    """The CLI module has no common Spanish words in its text."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted((SRC / "cli").glob("*.py")))
    words = r"Sin cambios|guardado|Regresiones|Ciclos|Archivos|Errores|Ejecuta|sin datos"
    assert not re.search(words, text, re.IGNORECASE)
