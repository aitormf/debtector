"""Parser registry and public re-exports for the parser sub-package."""

from __future__ import annotations

from ..models import EdgeInfo, NodeInfo
from .base import LanguageParser
from .js_parser import JavaScriptParser
from .python_parser import PythonParser


class ParserRegistry:
    """Registry that maps source files to the appropriate language parser.

    Parsers are registered at construction time.  The registry is the single
    point of contact between the :class:`~debtector.indexer.Indexer` and the
    concrete language parsers.
    """

    def __init__(self) -> None:
        """Initialize the registry with all built-in parsers."""
        self._parsers: list[LanguageParser] = [
            PythonParser(),
            JavaScriptParser(),
        ]

    def get_parser(self, file_path: str) -> LanguageParser | None:
        """Return the parser that can handle *file_path*, or ``None``.

        Args:
            file_path: Path to the source file (only the extension is used).

        Returns:
            The first registered :class:`LanguageParser` whose
            :meth:`~LanguageParser.can_parse` returns ``True``, or ``None``
            if no parser supports the file type.
        """
        for parser in self._parsers:
            if parser.can_parse(file_path):
                return parser
        return None

    def parse(self, file_path: str) -> tuple[list[NodeInfo], list[EdgeInfo]] | None:
        """Parse *file_path* using the appropriate registered parser.

        Args:
            file_path: Absolute path to the source file.

        Returns:
            ``(nodes, edges)`` tuple on success, or ``None`` if no parser
            supports the file type.
        """
        parser = self.get_parser(file_path)
        if parser:
            return parser.parse(file_path)
        return None

    @property
    def supported_extensions(self) -> list[str]:
        """List of all file extensions handled by registered parsers.

        Returns:
            Flat list of extension strings (e.g. ``[".py", ".js", ".ts"]``).
        """
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
