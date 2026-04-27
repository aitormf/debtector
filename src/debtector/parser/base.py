"""Abstract base class for language parsers.

Each parser produces lists of NodeInfo and EdgeInfo that the GraphStore
consumes directly.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path

from ..models import EdgeInfo, NodeInfo


class LanguageParser(ABC):
    """Abstract base class that all language-specific parsers must implement.

    Subclasses must define :attr:`language`, :attr:`extensions`, and
    :meth:`parse`.  Helper methods :meth:`file_hash` and :meth:`read_source`
    are provided for convenience.
    """

    @property
    @abstractmethod
    def language(self) -> str:
        """Human-readable language identifier (e.g. ``"python"``, ``"typescript"``)."""
        ...

    @property
    @abstractmethod
    def extensions(self) -> list[str]:
        """File extensions handled by this parser (e.g. ``[".py"]``)."""
        ...

    @abstractmethod
    def parse(self, file_path: str) -> tuple[list[NodeInfo], list[EdgeInfo]]:
        """Parse a source file and return its structural graph data.

        Args:
            file_path: Absolute path to the source file to parse.

        Returns:
            A tuple ``(nodes, edges)`` ready to be stored via
            :meth:`~debtector.graph_store.GraphStore.store_file`.
        """
        ...

    def can_parse(self, file_path: str) -> bool:
        """Return True if this parser handles the given file's extension.

        Args:
            file_path: Path to the file (only the suffix is examined).

        Returns:
            ``True`` when the file extension is in :attr:`extensions`.
        """
        return Path(file_path).suffix in self.extensions

    @staticmethod
    def file_hash(file_path: str) -> str:
        """Compute the SHA-256 hex digest of a file's contents.

        Args:
            file_path: Absolute path to the file.

        Returns:
            64-character lowercase hex string of the SHA-256 digest.
        """
        content = Path(file_path).read_bytes()
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def read_source(file_path: str) -> bytes:
        """Read and return the raw bytes of a source file.

        Args:
            file_path: Absolute path to the file.

        Returns:
            Raw file contents as bytes, suitable for passing to a tree-sitter parser.
        """
        return Path(file_path).read_bytes()
