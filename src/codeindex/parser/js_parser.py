"""
Parser de JavaScript/TypeScript usando Tree-sitter.

Produce NodeInfo y EdgeInfo con qualified_names, incluyendo aristas
CONTAINS, IMPORTS_FROM, HAS_METHOD e INHERITS.
"""

from __future__ import annotations

import structlog
from tree_sitter_language_pack import get_parser

from ..models import EdgeInfo, EdgeKind, NodeInfo, NodeKind, make_qualified_name
from .base import LanguageParser

log = structlog.get_logger()


class JavaScriptParser(LanguageParser):
    def __init__(self):
        self._parser = get_parser("typescript")

    @property
    def language(self) -> str:
        return "javascript"

    @property
    def extensions(self) -> list[str]:
        return [".js", ".jsx", ".ts", ".tsx"]

    def parse(self, file_path: str) -> tuple[list[NodeInfo], list[EdgeInfo]]:
        lang = "typescript" if file_path.endswith((".ts", ".tsx")) else "javascript"
        log.debug("parsing_file", file=file_path, language=lang)
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
                language=lang,
            )
        )

        self._extract_imports(root, source, file_path, file_qn, edges)
        self._extract_symbols(root, source, file_path, file_qn, lang, nodes, edges, parent=None)

        return nodes, edges

    # ──────────────────────────────────────────────
    # Imports
    # ──────────────────────────────────────────────

    def _extract_imports(
        self, root, source: bytes, file_path: str, file_qn: str, edges: list[EdgeInfo]
    ):
        for node in self._walk(root):
            if node.type == "import_statement":
                module = self._get_import_source(node, source)
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
            elif node.type == "lexical_declaration":
                text = self._text(node, source)
                if "require(" in text:
                    module = self._get_require_source(node, source)
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

    def _get_import_source(self, node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "string":
                return self._text(child, source).strip("'\"")
        return None

    def _get_require_source(self, node, source: bytes) -> str | None:
        for child in self._walk(node):
            if child.type == "string" and child.parent and child.parent.type == "arguments":
                return self._text(child, source).strip("'\"")
        return None

    # ──────────────────────────────────────────────
    # Símbolos
    # ──────────────────────────────────────────────

    def _extract_symbols(
        self,
        node,
        source: bytes,
        file_path: str,
        file_qn: str,
        lang: str,
        nodes: list[NodeInfo],
        edges: list[EdgeInfo],
        parent: str | None,
    ):
        for child in node.children:
            actual = child

            # Unwrap export
            if child.type == "export_statement":
                for sub in child.children:
                    if sub.type in (
                        "class_declaration",
                        "function_declaration",
                        "lexical_declaration",
                    ):
                        actual = sub
                        break

            if actual.type == "class_declaration":
                name = self._get_name(actual, source)
                qn = make_qualified_name(file_path, name, NodeKind.CLASS, parent)
                sig = self._first_line(actual, source).split("{")[0].strip()

                nodes.append(
                    NodeInfo(
                        kind=NodeKind.CLASS,
                        name=name,
                        qualified_name=qn,
                        file_path=file_path,
                        line_start=actual.start_point[0] + 1,
                        line_end=actual.end_point[0] + 1,
                        language=lang,
                        parent_name=parent,
                        signature=sig,
                    )
                )
                edges.append(
                    EdgeInfo(
                        kind=EdgeKind.CONTAINS,
                        source=file_qn,
                        target=qn,
                        file_path=file_path,
                        line=actual.start_point[0] + 1,
                    )
                )

                # Herencia
                for base in self._get_extends(actual, source):
                    edges.append(
                        EdgeInfo(
                            kind=EdgeKind.INHERITS,
                            source=qn,
                            target=base,
                            file_path=file_path,
                            line=actual.start_point[0] + 1,
                        )
                    )

                # Métodos
                body = self._get_class_body(actual)
                if body:
                    for member in body.children:
                        if member.type == "method_definition":
                            mname = self._get_name(member, source)
                            mqn = make_qualified_name(file_path, mname, NodeKind.METHOD, name)
                            msig = self._first_line(member, source).split("{")[0].strip()

                            nodes.append(
                                NodeInfo(
                                    kind=NodeKind.METHOD,
                                    name=mname,
                                    qualified_name=mqn,
                                    file_path=file_path,
                                    line_start=member.start_point[0] + 1,
                                    line_end=member.end_point[0] + 1,
                                    language=lang,
                                    parent_name=name,
                                    signature=msig,
                                )
                            )
                            edges.append(
                                EdgeInfo(
                                    kind=EdgeKind.HAS_METHOD,
                                    source=qn,
                                    target=mqn,
                                    file_path=file_path,
                                    line=member.start_point[0] + 1,
                                )
                            )

            elif actual.type == "function_declaration":
                name = self._get_name(actual, source)
                qn = make_qualified_name(file_path, name, NodeKind.FUNCTION, parent)
                sig = self._first_line(actual, source).split("{")[0].strip()

                nodes.append(
                    NodeInfo(
                        kind=NodeKind.FUNCTION,
                        name=name,
                        qualified_name=qn,
                        file_path=file_path,
                        line_start=actual.start_point[0] + 1,
                        line_end=actual.end_point[0] + 1,
                        language=lang,
                        parent_name=parent,
                        signature=sig,
                    )
                )
                edges.append(
                    EdgeInfo(
                        kind=EdgeKind.CONTAINS,
                        source=file_qn,
                        target=qn,
                        file_path=file_path,
                        line=actual.start_point[0] + 1,
                    )
                )

            elif actual.type == "lexical_declaration" and not parent:
                # Arrow functions: const fn = () => {}
                self._extract_arrow_fns(actual, source, file_path, file_qn, lang, nodes, edges)

    def _extract_arrow_fns(
        self,
        node,
        source: bytes,
        file_path: str,
        file_qn: str,
        lang: str,
        nodes: list[NodeInfo],
        edges: list[EdgeInfo],
    ):
        for child in node.children:
            if child.type == "variable_declarator":
                name = None
                has_arrow = False
                for sub in child.children:
                    if sub.type == "identifier":
                        name = self._text(sub, source)
                    elif sub.type == "arrow_function":
                        has_arrow = True
                if name and has_arrow:
                    qn = make_qualified_name(file_path, name, NodeKind.FUNCTION)
                    sig = self._first_line(node, source).strip()
                    nodes.append(
                        NodeInfo(
                            kind=NodeKind.FUNCTION,
                            name=name,
                            qualified_name=qn,
                            file_path=file_path,
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                            language=lang,
                            signature=sig,
                        )
                    )
                    edges.append(
                        EdgeInfo(
                            kind=EdgeKind.CONTAINS,
                            source=file_qn,
                            target=qn,
                            file_path=file_path,
                            line=node.start_point[0] + 1,
                        )
                    )

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def _get_name(self, node, source: bytes) -> str:
        # type_identifier is used for class names in TypeScript
        for child in node.children:
            if child.type in ("identifier", "property_identifier", "type_identifier"):
                return self._text(child, source)
        return "<unknown>"

    def _get_class_body(self, node):
        for child in node.children:
            if child.type == "class_body":
                return child
        return None

    def _get_extends(self, class_node, source: bytes) -> list[str]:
        for child in class_node.children:
            if child.type == "class_heritage":
                for sub in child.children:
                    if sub.type in ("identifier", "type_identifier"):
                        return [self._text(sub, source)]
                    # TypeScript wraps the base class in an extends_clause node
                    if sub.type == "extends_clause":
                        for inner in sub.children:
                            if inner.type in ("identifier", "type_identifier"):
                                return [self._text(inner, source)]
        return []

    def _first_line(self, node, source: bytes) -> str:
        return self._text(node, source).split("\n")[0]

    @staticmethod
    def _text(node, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def _walk(node):
        for child in node.children:
            yield child
            yield from JavaScriptParser._walk(child)
