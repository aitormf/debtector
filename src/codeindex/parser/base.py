"""
Clase base abstracta para los parsers de lenguaje.

Cada parser produce listas de NodeInfo y EdgeInfo que el GraphStore
consume directamente.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path

from ..models import EdgeInfo, NodeInfo


class LanguageParser(ABC):
    @property
    @abstractmethod
    def language(self) -> str: ...

    @property
    @abstractmethod
    def extensions(self) -> list[str]: ...

    @abstractmethod
    def parse(self, file_path: str) -> tuple[list[NodeInfo], list[EdgeInfo]]:
        """
        Parsea un archivo y devuelve nodos y aristas.

        Returns:
            Tupla (nodes, edges) listos para almacenar en el GraphStore.
        """
        ...

    def can_parse(self, file_path: str) -> bool:
        return Path(file_path).suffix in self.extensions

    @staticmethod
    def file_hash(file_path: str) -> str:
        content = Path(file_path).read_bytes()
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def read_source(file_path: str) -> bytes:
        return Path(file_path).read_bytes()
