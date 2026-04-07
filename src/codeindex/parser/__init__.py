"""Registro de parsers disponibles."""

from __future__ import annotations

from ..models import EdgeInfo, NodeInfo
from .base import LanguageParser
from .js_parser import JavaScriptParser
from .python_parser import PythonParser


class ParserRegistry:
    """Dado un archivo, encuentra el parser correcto y lo parsea."""

    def __init__(self):
        self._parsers: list[LanguageParser] = [
            PythonParser(),
            JavaScriptParser(),
        ]

    def get_parser(self, file_path: str) -> LanguageParser | None:
        for parser in self._parsers:
            if parser.can_parse(file_path):
                return parser
        return None

    def parse(self, file_path: str) -> tuple[list[NodeInfo], list[EdgeInfo]] | None:
        parser = self.get_parser(file_path)
        if parser:
            return parser.parse(file_path)
        return None

    @property
    def supported_extensions(self) -> list[str]:
        exts = []
        for p in self._parsers:
            exts.extend(p.extensions)
        return exts


__all__ = [
    "ParserRegistry",
    "LanguageParser",
    "PythonParser",
    "JavaScriptParser",
]
