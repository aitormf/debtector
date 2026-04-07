"""
Parser de Python usando Tree-sitter.

Produce NodeInfo y EdgeInfo con qualified_names. Además de extraer la
estructura, genera aristas CONTAINS (archivo→clase, clase→método),
IMPORTS_FROM (archivo→módulo) y HAS_METHOD (clase→método).
"""

from __future__ import annotations

from tree_sitter_language_pack import get_parser

from ..models import EdgeInfo, EdgeKind, NodeInfo, NodeKind, make_qualified_name
from .base import LanguageParser


class PythonParser(LanguageParser):
    def __init__(self):
        self._parser = get_parser("python")

    @property
    def language(self) -> str:
        return "python"

    @property
    def extensions(self) -> list[str]:
        return [".py"]

    def parse(self, file_path: str) -> tuple[list[NodeInfo], list[EdgeInfo]]:
        source = self.read_source(file_path)
        tree = self._parser.parse(source)
        root = tree.root_node

        nodes: list[NodeInfo] = []
        edges: list[EdgeInfo] = []

        # Nodo del archivo
        file_qn = make_qualified_name(file_path, file_path, NodeKind.FILE)
        nodes.append(
            NodeInfo(
                kind=NodeKind.FILE,
                name=file_path.split("/")[-1],
                qualified_name=file_qn,
                file_path=file_path,
                line_start=1,
                line_end=root.end_point[0] + 1,
                language=self.language,
            )
        )

        # Extraer imports
        self._extract_imports(root, source, file_path, file_qn, edges)

        # Extraer clases, funciones, métodos
        self._extract_symbols(root, source, file_path, file_qn, nodes, edges, parent=None)

        return nodes, edges

    # ──────────────────────────────────────────────
    # Imports
    # ──────────────────────────────────────────────

    def _extract_imports(
        self, root, source: bytes, file_path: str, file_qn: str, edges: list[EdgeInfo]
    ):
        for node in self._walk(root):
            if node.type == "import_statement":
                module = self._parse_import_module(node, source)
                if module:
                    edges.append(
                        EdgeInfo(
                            kind=EdgeKind.IMPORTS_FROM,
                            source=file_qn,
                            target=module,
                            file_path=file_path,
                            line=node.start_point[0] + 1,
                        )
                    )

            elif node.type == "import_from_statement":
                module = self._parse_from_module(node, source)
                if module:
                    edges.append(
                        EdgeInfo(
                            kind=EdgeKind.IMPORTS_FROM,
                            source=file_qn,
                            target=module,
                            file_path=file_path,
                            line=node.start_point[0] + 1,
                        )
                    )

    def _parse_import_module(self, node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "dotted_name":
                return self._text(child, source)
            elif child.type == "aliased_import":
                for sub in child.children:
                    if sub.type == "dotted_name":
                        return self._text(sub, source)
        return None

    def _parse_from_module(self, node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "dotted_name":
                return self._text(child, source)
            elif child.type == "relative_import":
                for sub in child.children:
                    if sub.type == "dotted_name":
                        return self._text(sub, source)
        return None

    # ──────────────────────────────────────────────
    # Símbolos (clases, funciones, métodos)
    # ──────────────────────────────────────────────

    def _extract_symbols(
        self,
        node,
        source: bytes,
        file_path: str,
        file_qn: str,
        nodes: list[NodeInfo],
        edges: list[EdgeInfo],
        parent: str | None,
    ):
        for child in node.children:
            decorators = []

            if child.type == "decorated_definition":
                decorators = self._get_decorators(child, source)
                for sub in child.children:
                    if sub.type in ("class_definition", "function_definition"):
                        child = sub
                        break

            if child.type == "class_definition":
                name = self._get_name(child, source)
                kind = NodeKind.CLASS
                qn = make_qualified_name(file_path, name, kind, parent)
                signature = self._get_signature(child, source)
                docstring = self._get_docstring(child, source)

                nodes.append(
                    NodeInfo(
                        kind=kind,
                        name=name,
                        qualified_name=qn,
                        file_path=file_path,
                        line_start=child.start_point[0] + 1,
                        line_end=child.end_point[0] + 1,
                        language=self.language,
                        parent_name=parent,
                        signature=signature,
                        docstring=docstring,
                        decorators=decorators,
                    )
                )

                # Arista: archivo CONTAINS clase
                edges.append(
                    EdgeInfo(
                        kind=EdgeKind.CONTAINS,
                        source=file_qn,
                        target=qn,
                        file_path=file_path,
                        line=child.start_point[0] + 1,
                    )
                )

                # Herencia
                for base in self._get_bases(child, source):
                    edges.append(
                        EdgeInfo(
                            kind=EdgeKind.INHERITS,
                            source=qn,
                            target=base,
                            file_path=file_path,
                            line=child.start_point[0] + 1,
                        )
                    )

                # Recursión para métodos dentro de la clase
                body = self._get_body(child)
                if body:
                    self._extract_symbols(
                        body, source, file_path, file_qn, nodes, edges, parent=name
                    )

            elif child.type == "function_definition":
                name = self._get_name(child, source)
                kind = NodeKind.METHOD if parent else NodeKind.FUNCTION
                qn = make_qualified_name(file_path, name, kind, parent)
                signature = self._get_signature(child, source)
                docstring = self._get_docstring(child, source)

                nodes.append(
                    NodeInfo(
                        kind=kind,
                        name=name,
                        qualified_name=qn,
                        file_path=file_path,
                        line_start=child.start_point[0] + 1,
                        line_end=child.end_point[0] + 1,
                        language=self.language,
                        parent_name=parent,
                        signature=signature,
                        docstring=docstring,
                        decorators=decorators,
                    )
                )

                # Arista: CONTAINS o HAS_METHOD
                if parent:
                    parent_qn = make_qualified_name(file_path, parent, NodeKind.CLASS)
                    edges.append(
                        EdgeInfo(
                            kind=EdgeKind.HAS_METHOD,
                            source=parent_qn,
                            target=qn,
                            file_path=file_path,
                            line=child.start_point[0] + 1,
                        )
                    )
                else:
                    edges.append(
                        EdgeInfo(
                            kind=EdgeKind.CONTAINS,
                            source=file_qn,
                            target=qn,
                            file_path=file_path,
                            line=child.start_point[0] + 1,
                        )
                    )

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def _get_name(self, node, source: bytes) -> str:
        for child in node.children:
            if child.type == "identifier":
                return self._text(child, source)
        return "<unknown>"

    def _get_signature(self, node, source: bytes) -> str:
        line = source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
        depth = 0
        for i, char in enumerate(line):
            if char in "([":
                depth += 1
            elif char in ")]":
                depth -= 1
            elif char == ":" and depth == 0:
                return line[:i].strip()
        return line.split("\n")[0].strip()

    def _get_body(self, node):
        for child in node.children:
            if child.type == "block":
                return child
        return None

    def _get_docstring(self, node, source: bytes) -> str | None:
        body = self._get_body(node)
        if not body or not body.children:
            return None
        first = body.children[0]
        if first.type == "expression_statement" and first.children:
            expr = first.children[0]
            if expr.type == "string":
                text = self._text(expr, source)
                for q in ('"""', "'''", '"', "'"):
                    if text.startswith(q) and text.endswith(q):
                        return text[len(q) : -len(q)].strip()
        return None

    def _get_decorators(self, decorated_node, source: bytes) -> list[str]:
        return [
            self._text(child, source)
            for child in decorated_node.children
            if child.type == "decorator"
        ]

    def _get_bases(self, class_node, source: bytes) -> list[str]:
        """Extrae las clases base de una class_definition."""
        bases = []
        for child in class_node.children:
            if child.type == "argument_list":
                for arg in child.children:
                    if arg.type == "identifier":
                        bases.append(self._text(arg, source))
                    elif arg.type == "attribute":
                        bases.append(self._text(arg, source))
        return bases

    @staticmethod
    def _text(node, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def _walk(node):
        for child in node.children:
            yield child
            yield from PythonParser._walk(child)
