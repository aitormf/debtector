"""
Parser de JavaScript/TypeScript usando Tree-sitter.

Produce NodeInfo y EdgeInfo con qualified_names, incluyendo aristas
CONTAINS, IMPORTS_FROM, HAS_METHOD e INHERITS.
"""

from __future__ import annotations

import structlog
from tree_sitter_language_pack import get_parser

from ..models import EdgeInfo, EdgeKind, NodeInfo, NodeKind, make_qualified_name
from ..utils import is_test_file
from .base import LanguageParser

log = structlog.get_logger()


class JavaScriptParser(LanguageParser):
    """Tree-sitter–based parser for JavaScript and TypeScript source files.

    Extracts files, classes, functions, and methods as nodes, and produces
    CONTAINS, HAS_METHOD, IMPORTS_FROM, and INHERITS edges.  Uses the
    TypeScript grammar under the hood, which is a superset of JavaScript.
    """

    def __init__(self):
        """Initialize the parser with the tree-sitter TypeScript grammar."""
        self._parser = get_parser("typescript")

    @property
    def language(self) -> str:
        """Return ``"javascript"``."""
        return "javascript"

    @property
    def extensions(self) -> list[str]:
        """Return ``[".js", ".jsx", ".ts", ".tsx"]``."""
        return [".js", ".jsx", ".ts", ".tsx"]

    def parse(self, file_path: str) -> tuple[list[NodeInfo], list[EdgeInfo]]:
        """Parse a JavaScript or TypeScript file and return its structural graph data.

        Args:
            file_path: Absolute path to the ``.js``, ``.jsx``, ``.ts``, or ``.tsx`` file.

        Returns:
            A ``(nodes, edges)`` tuple where *nodes* includes one File node plus
            Class, Function, and Method nodes, and *edges* includes CONTAINS,
            HAS_METHOD, IMPORTS_FROM, and INHERITS relationships.  The
            ``language`` field on each node is set to ``"typescript"`` for
            ``.ts``/``.tsx`` files, and ``"javascript"`` otherwise.
        """
        lang = "typescript" if file_path.endswith((".ts", ".tsx")) else "javascript"
        log.debug("parsing_file", file=file_path, language=lang)
        source = self.read_source(file_path)
        tree = self._parser.parse(source)
        root = tree.root_node

        nodes: list[NodeInfo] = []
        edges: list[EdgeInfo] = []

        # Nodo del archivo
        file_qn = make_qualified_name(file_path, file_path, NodeKind.FILE)
        module_docstring = self._get_module_docstring(root, source)
        nodes.append(
            NodeInfo(
                kind=NodeKind.FILE,
                name=file_path.split("/")[-1],
                qualified_name=file_qn,
                file_path=file_path,
                line_start=1,
                line_end=root.end_point[0] + 1,
                language=lang,
                docstring=module_docstring,
            )
        )

        self._extract_imports(root, source, file_path, file_qn, edges)
        uses_type_seen: set[str] = set()
        self._extract_symbols(
            root,
            source,
            file_path,
            file_qn,
            lang,
            nodes,
            edges,
            parent=None,
            uses_type_seen=uses_type_seen,
        )

        # Segunda pasada: aristas CALLS (requiere índice completo de símbolos)
        symbol_index = self._build_symbol_index(nodes)
        self._extract_file_calls(root, source, file_path, symbol_index, edges, parent=None)

        return nodes, edges

    # ──────────────────────────────────────────────
    # Imports
    # ──────────────────────────────────────────────

    def _extract_imports(
        self, root, source: bytes, file_path: str, file_qn: str, edges: list[EdgeInfo]
    ):
        """Walk the AST and append IMPORTS_FROM edges for every import statement.

        Handles ES module ``import`` statements and CommonJS ``require()`` calls
        inside ``lexical_declaration`` nodes.

        Args:
            root: The root tree-sitter node of the parsed file.
            source: Raw source bytes of the file.
            file_path: Absolute path to the source file.
            file_qn: Qualified name of the file node (used as edge source).
            edges: Mutable list to which new :class:`~debtector.models.EdgeInfo`
                objects are appended in-place.
        """
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
        """Extract the module specifier string from an ES ``import_statement`` node.

        Args:
            node: A tree-sitter ``import_statement`` node.
            source: Raw source bytes.

        Returns:
            The module specifier without surrounding quotes (e.g. ``"react"`` or
            ``"./utils"``), or ``None`` if not found.
        """
        for child in node.children:
            if child.type == "string":
                return self._text(child, source).strip("'\"")
        return None

    def _get_require_source(self, node, source: bytes) -> str | None:
        """Extract the module specifier from a ``require()`` call inside a declaration.

        Looks for a ``string`` node whose parent is an ``arguments`` node,
        which is the pattern generated by ``const x = require('...')``.

        Args:
            node: A tree-sitter ``lexical_declaration`` node.
            source: Raw source bytes.

        Returns:
            The module specifier without quotes, or ``None`` if not found.
        """
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
        uses_type_seen: set[str] | None = None,
    ):
        """Extract class, function, and method nodes from the direct children of *node*.

        Handles ``export_statement`` wrappers transparently, unwrapping to the
        inner declaration before dispatching.  Class bodies are visited to
        capture ``method_definition`` children.  Arrow functions stored in
        ``lexical_declaration`` nodes are delegated to
        :meth:`_extract_arrow_fns`.

        Args:
            node: The tree-sitter node whose children to inspect.
            source: Raw source bytes of the file.
            file_path: Absolute path to the source file.
            file_qn: Qualified name of the file node (used as CONTAINS edge source).
            lang: Language label to attach to nodes (``"javascript"`` or
                ``"typescript"``).
            nodes: Mutable list to which new :class:`~debtector.models.NodeInfo`
                objects are appended in-place.
            edges: Mutable list to which new :class:`~debtector.models.EdgeInfo`
                objects are appended in-place.
            parent: Name of the enclosing class when processing a class body,
                or ``None`` at module level.
            uses_type_seen: Set compartido a nivel de archivo para dedup O(1)
                de USES_TYPE. Se crea en ``parse()`` y se reutiliza en toda
                la extracción del archivo.
        """
        if uses_type_seen is None:
            uses_type_seen = set()
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

                            # Aristas USES_TYPE desde las anotaciones de tipo del método
                            self._extract_uses_type_ts(
                                member,
                                source,
                                file_path,
                                file_qn,
                                member.start_point[0] + 1,
                                edges,
                                uses_type_seen,
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

                # Aristas USES_TYPE desde las anotaciones de tipo de la función
                self._extract_uses_type_ts(
                    actual,
                    source,
                    file_path,
                    file_qn,
                    actual.start_point[0] + 1,
                    edges,
                    uses_type_seen,
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
        """Extract arrow function nodes from a ``lexical_declaration`` node.

        Looks for patterns such as ``const fn = () => { ... }`` by checking
        for ``variable_declarator`` children that contain an ``arrow_function``
        sub-child.

        Args:
            node: A tree-sitter ``lexical_declaration`` node.
            source: Raw source bytes.
            file_path: Absolute path to the source file.
            file_qn: Qualified name of the file node (used as CONTAINS edge source).
            lang: Language label to attach to nodes.
            nodes: Mutable list to which new :class:`~debtector.models.NodeInfo`
                objects are appended in-place.
            edges: Mutable list to which new :class:`~debtector.models.EdgeInfo`
                objects are appended in-place.
        """
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
        """Return the identifier name of a class, function, or method node.

        Checks for ``identifier``, ``property_identifier``, and
        ``type_identifier`` child node types to support both JavaScript and
        TypeScript naming conventions.

        Args:
            node: A tree-sitter declaration or definition node.
            source: Raw source bytes.

        Returns:
            The name as a string, or ``"<unknown>"`` if no identifier child
            is found.
        """
        # type_identifier is used for class names in TypeScript
        for child in node.children:
            if child.type in ("identifier", "property_identifier", "type_identifier"):
                return self._text(child, source)
        return "<unknown>"

    def _get_class_body(self, node):
        """Return the ``class_body`` child of a class declaration node.

        Args:
            node: A tree-sitter ``class_declaration`` node.

        Returns:
            The ``class_body`` child node, or ``None`` if absent.
        """
        for child in node.children:
            if child.type == "class_body":
                return child
        return None

    def _get_extends(self, class_node, source: bytes) -> list[str]:
        """Extract base class names from a class declaration.

        Handles both the JavaScript pattern (``class_heritage`` → identifier
        directly) and the TypeScript pattern (``class_heritage`` →
        ``extends_clause`` → identifier).

        Args:
            class_node: A tree-sitter ``class_declaration`` node.
            source: Raw source bytes.

        Returns:
            List of base class name strings.  Returns an empty list if the
            class has no ``extends`` clause.
        """
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

    # ──────────────────────────────────────────────
    # USES_TYPE edge extraction (TypeScript)
    # ──────────────────────────────────────────────

    def _extract_uses_type_ts(
        self,
        func_node,
        source: bytes,
        file_path: str,
        file_qn: str,
        line: int,
        edges: list[EdgeInfo],
        uses_type_seen: set[str],
    ) -> None:
        """Emit USES_TYPE edges for uppercase types referenced in a TS function/method signature.

        Inspects ``type_annotation`` children of parameters and the function
        itself (return type).  Only type names starting with an uppercase letter
        are emitted.  Duplicate edges within the same file are suppressed
        via *uses_type_seen* (O(1) lookup).

        Args:
            func_node: A tree-sitter ``function_declaration`` or ``method_definition`` node.
            source: Raw source bytes of the file.
            file_path: Absolute path to the source file.
            file_qn: Qualified name of the file node (used as edge source).
            line: Line number of the function/method definition.
            edges: Mutable list to which new :class:`~debtector.models.EdgeInfo`
                objects are appended in-place.
            uses_type_seen: Set de tipos ya emitidos para este archivo.
                Se muta en-place. Permite dedup en O(1) sin escanear ``edges``.
        """
        type_names: set[str] = set()

        for child in self._walk(func_node):
            if child.type == "type_annotation":
                type_names.update(self._collect_ts_type_identifiers(child, source))

        for type_name in type_names:
            if type_name not in uses_type_seen:
                edges.append(
                    EdgeInfo(
                        kind=EdgeKind.USES_TYPE,
                        source=file_qn,
                        target=type_name,
                        file_path=file_path,
                        line=line,
                    )
                )
                uses_type_seen.add(type_name)

    def _collect_ts_type_identifiers(self, type_node, source: bytes) -> set[str]:
        """Recursively extract uppercase type identifiers from a TypeScript type annotation.

        Handles ``type_identifier``, ``generic_type``, and plain ``identifier``
        nodes within the annotation subtree.

        Args:
            type_node: A tree-sitter ``type_annotation`` node.
            source: Raw source bytes.

        Returns:
            Set of type name strings starting with an uppercase letter.
        """
        names: set[str] = set()
        for node in self._walk(type_node):
            if node.type in ("type_identifier", "identifier"):
                text = self._text(node, source)
                if text and text[0].isupper():
                    names.add(text)
        return names

    # ──────────────────────────────────────────────
    # CALLS edge extraction (second pass)
    # ──────────────────────────────────────────────

    @staticmethod
    def _build_symbol_index(nodes: list[NodeInfo]) -> dict[str, list[str]]:
        """Build a lookup from short name (and ``Class.name``) to qualified names.

        Args:
            nodes: All nodes produced by the first-pass symbol extraction.

        Returns:
            Dict mapping ``name`` and ``ClassName.name`` keys to lists of
            qualified name strings.
        """
        index: dict[str, list[str]] = {}
        for node in nodes:
            if node.kind == NodeKind.FILE:
                continue
            index.setdefault(node.name, []).append(node.qualified_name)
            if node.parent_name:
                compound = f"{node.parent_name}.{node.name}"
                index.setdefault(compound, []).append(node.qualified_name)
        return index

    def _extract_file_calls(
        self,
        node,
        source: bytes,
        file_path: str,
        symbol_index: dict[str, list[str]],
        edges: list[EdgeInfo],
        parent: str | None,
    ) -> None:
        """Second-pass walk that emits CALLS edges for resolved call targets.

        Mirrors the structure of :meth:`_extract_symbols` to determine the
        current caller context (class / function name) before descending into
        bodies.

        Args:
            node: AST node whose children to inspect.
            source: Raw source bytes.
            file_path: Absolute path to the source file.
            symbol_index: Name-to-qualified-name lookup from the first pass.
            edges: Mutable list to which new CALLS edges are appended.
            parent: Enclosing class name, or ``None`` at module level.
        """
        for child in node.children:
            actual = child
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
                class_name = self._get_name(actual, source)
                body = self._get_class_body(actual)
                if body:
                    for member in body.children:
                        if member.type == "method_definition":
                            mname = self._get_name(member, source)
                            caller_qn = make_qualified_name(
                                file_path, mname, NodeKind.METHOD, class_name
                            )
                            self._extract_calls(
                                member,
                                source,
                                file_path,
                                caller_qn,
                                class_name,
                                symbol_index,
                                edges,
                            )

            elif actual.type == "function_declaration":
                func_name = self._get_name(actual, source)
                caller_qn = make_qualified_name(file_path, func_name, NodeKind.FUNCTION, parent)
                self._extract_calls(
                    actual, source, file_path, caller_qn, parent, symbol_index, edges
                )

            elif actual.type == "lexical_declaration" and not parent:
                # Arrow functions
                for sub in actual.children:
                    if sub.type == "variable_declarator":
                        func_name = None
                        arrow_node = None
                        for s in sub.children:
                            if s.type == "identifier":
                                func_name = self._text(s, source)
                            elif s.type == "arrow_function":
                                arrow_node = s
                        if func_name and arrow_node:
                            caller_qn = make_qualified_name(file_path, func_name, NodeKind.FUNCTION)
                            self._extract_calls(
                                arrow_node,
                                source,
                                file_path,
                                caller_qn,
                                None,
                                symbol_index,
                                edges,
                            )

    def _extract_calls(
        self,
        func_node,
        source: bytes,
        file_path: str,
        caller_qn: str,
        caller_class: str | None,
        symbol_index: dict[str, list[str]],
        edges: list[EdgeInfo],
    ) -> None:
        """Walk a function/method node and emit CALLS edges for resolved targets.

        Args:
            func_node: The function, method, or arrow-function AST node.
            source: Raw source bytes.
            file_path: Absolute path to the source file.
            caller_qn: Qualified name of the enclosing function or method.
            caller_class: Name of the enclosing class, or ``None``.
            symbol_index: Name-to-qualified-name lookup from the first pass.
            edges: Mutable list to which new CALLS edges are appended.
        """
        in_test = is_test_file(file_path)
        for node in self._walk(func_node):
            if node.type != "call_expression":
                continue
            func_child = node.child_by_field_name("function")
            if func_child is None:
                continue
            callee_qn = self._resolve_callee(func_child, source, caller_class, symbol_index)
            if callee_qn and callee_qn != caller_qn:
                edges.append(
                    EdgeInfo(
                        kind=EdgeKind.CALLS,
                        source=caller_qn,
                        target=callee_qn,
                        file_path=file_path,
                        line=node.start_point[0] + 1,
                    )
                )
            elif callee_qn is None and in_test:
                raw = self._get_raw_callee_name(func_child, source)
                if raw:
                    edges.append(
                        EdgeInfo(
                            kind=EdgeKind.CALLS,
                            source=caller_qn,
                            target=raw,
                            file_path=file_path,
                            line=node.start_point[0] + 1,
                            extra={"unresolved": True},
                        )
                    )

    def _resolve_callee(
        self,
        func_node,
        source: bytes,
        caller_class: str | None,
        symbol_index: dict[str, list[str]],
    ) -> str | None:
        """Resolve a call's function node to a qualified name in the same file.

        Handles:

        * ``identifier`` — plain call (``helper()``) or constructor (``Service()``).
        * ``member_expression`` with ``this`` — intra-class call (``this.validate()``).
        * ``member_expression`` with a named object — explicit call
          (``Service.create()``).

        Args:
            func_node: The ``function`` field of a ``call_expression`` node.
            source: Raw source bytes.
            caller_class: Name of the enclosing class, or ``None``.
            symbol_index: Name-to-qualified-name lookup.

        Returns:
            Resolved qualified name, or ``None`` if unresolvable.
        """
        if func_node.type == "identifier":
            name = self._text(func_node, source)
            if caller_class:
                key = f"{caller_class}.{name}"
                if key in symbol_index:
                    return symbol_index[key][0]
            candidates = symbol_index.get(name, [])
            return candidates[0] if len(candidates) == 1 else None

        if func_node.type == "member_expression":
            obj_node = func_node.child_by_field_name("object")
            prop_node = func_node.child_by_field_name("property")
            if obj_node is None or prop_node is None:
                return None
            obj = self._text(obj_node, source)
            prop = self._text(prop_node, source)

            if obj == "this" and caller_class:
                key = f"{caller_class}.{prop}"
                candidates = symbol_index.get(key, [])
                return candidates[0] if candidates else None

            key = f"{obj}.{prop}"
            candidates = symbol_index.get(key, [])
            return candidates[0] if candidates else None

        return None

    def _get_raw_callee_name(self, func_node, source: bytes) -> str | None:
        """Extract the bare name of a callee without resolving to a qualified name.

        Used to capture cross-file call targets in test files so that
        :meth:`~debtector.graph_store.GraphStore.update_covers_edges` can later
        resolve them against the full node index.

        Args:
            func_node: The ``function`` field of a ``call_expression`` node.
            source: Raw source bytes.

        Returns:
            The bare callee name (e.g. ``"add"`` or ``"validate"``), or ``None``
            if no name can be extracted.
        """
        if func_node.type == "identifier":
            return self._text(func_node, source)
        if func_node.type == "member_expression":
            prop_node = func_node.child_by_field_name("property")
            if prop_node is not None:
                return self._text(prop_node, source)
        return None

    def _first_line(self, node, source: bytes) -> str:
        """Return the first source line covered by *node*.

        Args:
            node: Any tree-sitter node.
            source: Raw source bytes.

        Returns:
            The first line of the node's source text.
        """
        return self._text(node, source).split("\n")[0]

    def _get_module_docstring(self, root, source: bytes) -> str | None:
        """Extract a module-level JSDoc comment from the top of the file.

        Looks for the first ``comment`` node in the root whose text starts with
        ``/**`` — the conventional JSDoc block used to describe a module.

        Args:
            root: The tree-sitter root node of the parsed file.
            source: Raw source bytes.

        Returns:
            The comment text with ``/**``, ``*/``, leading ``*`` per line, and
            surrounding whitespace stripped; or ``None`` if no JSDoc is found.
        """
        for child in root.children:
            if child.type == "comment":
                text = self._text(child, source)
                if text.startswith("/**"):
                    # Strip /** ... */ and leading * per line
                    inner = text[3:]
                    if inner.endswith("*/"):
                        inner = inner[:-2]
                    lines = [ln.strip().lstrip("*").strip() for ln in inner.splitlines()]
                    return " ".join(ln for ln in lines if ln) or None
            elif child.type not in ("", "\n"):
                break
        return None

    @staticmethod
    def _text(node, source: bytes) -> str:
        """Return the UTF-8 text covered by *node* in *source*.

        Args:
            node: Any tree-sitter node.
            source: Raw source bytes of the file.

        Returns:
            Decoded string for the byte range ``[node.start_byte, node.end_byte)``.
        """
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def _walk(node):
        """Yield every descendant of *node* in depth-first order.

        Args:
            node: The tree-sitter node to start the traversal from.

        Yields:
            Each child and sub-child node in depth-first, left-to-right order.
        """
        for child in node.children:
            yield child
            yield from JavaScriptParser._walk(child)
