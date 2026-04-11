"""
Parser de Python usando Tree-sitter.

Produce NodeInfo y EdgeInfo con qualified_names. Además de extraer la
estructura, genera aristas CONTAINS (archivo→clase, clase→método),
IMPORTS_FROM (archivo→módulo) y HAS_METHOD (clase→método).
"""

from __future__ import annotations

import structlog
from tree_sitter_language_pack import get_parser

from ..models import EdgeInfo, EdgeKind, NodeInfo, NodeKind, make_qualified_name
from ..utils import is_test_file
from .base import LanguageParser

log = structlog.get_logger()


class PythonParser(LanguageParser):
    """Tree-sitter–based parser for Python source files.

    Extracts files, classes, functions, and methods as nodes, and produces
    CONTAINS, HAS_METHOD, IMPORTS_FROM, and INHERITS edges.
    """

    def __init__(self) -> None:
        """Initialize the parser with the tree-sitter Python grammar."""
        self._parser = get_parser("python")

    @property
    def language(self) -> str:
        """Return ``"python"``."""
        return "python"

    @property
    def extensions(self) -> list[str]:
        """Return ``[".py"]``."""
        return [".py"]

    def parse(self, file_path: str) -> tuple[list[NodeInfo], list[EdgeInfo]]:
        """Parse a Python file and return its structural graph data.

        Args:
            file_path: Absolute path to the ``.py`` file.

        Returns:
            A ``(nodes, edges)`` tuple where *nodes* includes one File node plus
            Class, Function, and Method nodes, and *edges* includes CONTAINS,
            HAS_METHOD, IMPORTS_FROM, and INHERITS relationships.
        """
        log.debug("parsing_file", file=file_path, language=self.language)
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
                language=self.language,
                docstring=module_docstring,
            )
        )

        # Extraer imports
        self._extract_imports(root, source, file_path, file_qn, edges)

        # Extraer clases, funciones, métodos
        self._extract_symbols(root, source, file_path, file_qn, nodes, edges, parent=None)

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

        Args:
            root: The root tree-sitter node of the parsed file.
            source: Raw source bytes of the file.
            file_path: Absolute path to the source file.
            file_qn: Qualified name of the file node (used as edge source).
            edges: Mutable list to which new :class:`~codeindex.models.EdgeInfo` objects
                are appended in-place.
        """
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
        """Extract the module name from an ``import_statement`` node.

        Handles both plain imports (``import os``) and aliased imports
        (``import numpy as np``).

        Args:
            node: A tree-sitter ``import_statement`` node.
            source: Raw source bytes.

        Returns:
            The dotted module name string, or ``None`` if it cannot be determined.
        """
        for child in node.children:
            if child.type == "dotted_name":
                return self._text(child, source)
            elif child.type == "aliased_import":
                for sub in child.children:
                    if sub.type == "dotted_name":
                        return self._text(sub, source)
        return None

    def _parse_from_module(self, node, source: bytes) -> str | None:
        """Extract the module name from an ``import_from_statement`` node.

        Handles both absolute (``from os.path import join``) and relative
        (``from .database import ConnectionPool``) imports.

        Args:
            node: A tree-sitter ``import_from_statement`` node.
            source: Raw source bytes.

        Returns:
            The dotted module name string (e.g. ``"os.path"`` or ``".database"``),
            or ``None`` if it cannot be determined.
        """
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
        """Recursively extract class, function, and method nodes from an AST subtree.

        Visits the direct children of *node*, handles ``decorated_definition``
        wrappers transparently, and recurses into class bodies to capture methods.

        Args:
            node: The tree-sitter node whose children to inspect.
            source: Raw source bytes of the file.
            file_path: Absolute path to the source file.
            file_qn: Qualified name of the file node (used as CONTAINS edge source).
            nodes: Mutable list to which new :class:`~codeindex.models.NodeInfo`
                objects are appended in-place.
            edges: Mutable list to which new :class:`~codeindex.models.EdgeInfo`
                objects are appended in-place.
            parent: Name of the enclosing class when recursing into a class body,
                or ``None`` at module level.
        """
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
    # CALLS edge extraction (second pass)
    # ──────────────────────────────────────────────

    @staticmethod
    def _build_symbol_index(nodes: list[NodeInfo]) -> dict[str, list[str]]:
        """Build a lookup from short name (and ``Class.name``) to qualified names.

        Used to resolve call targets to known symbols within the same file.

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
        """Second-pass AST walk that emits CALLS edges for resolved call targets.

        Mirrors the structure of :meth:`_extract_symbols` to identify which
        function or method is the caller, then delegates to
        :meth:`_extract_calls` for the body.

        Args:
            node: AST node whose children to inspect (root or class body).
            source: Raw source bytes.
            file_path: Absolute path to the source file.
            symbol_index: Name-to-qualified-name lookup from the first pass.
            edges: Mutable list to which new CALLS edges are appended.
            parent: Enclosing class name, or ``None`` at module level.
        """
        for child in node.children:
            actual = child
            if child.type == "decorated_definition":
                for sub in child.children:
                    if sub.type in ("class_definition", "function_definition"):
                        actual = sub
                        break

            if actual.type == "class_definition":
                class_name = self._get_name(actual, source)
                body = self._get_body(actual)
                if body:
                    self._extract_file_calls(
                        body, source, file_path, symbol_index, edges, parent=class_name
                    )

            elif actual.type == "function_definition":
                func_name = self._get_name(actual, source)
                kind = NodeKind.METHOD if parent else NodeKind.FUNCTION
                caller_qn = make_qualified_name(file_path, func_name, kind, parent)
                body = self._get_body(actual)
                if body:
                    self._extract_calls(
                        body, source, file_path, caller_qn, parent, symbol_index, edges
                    )

    def _extract_calls(
        self,
        body_node,
        source: bytes,
        file_path: str,
        caller_qn: str,
        caller_class: str | None,
        symbol_index: dict[str, list[str]],
        edges: list[EdgeInfo],
    ) -> None:
        """Walk a function body and emit CALLS edges for resolved call targets.

        Only emits edges for calls whose targets can be resolved to a known
        symbol in the same file.  Unresolved calls (e.g. external library
        calls, calls through variables) are silently skipped.

        Args:
            body_node: The ``block`` AST node of a function or method.
            source: Raw source bytes.
            file_path: Absolute path to the source file.
            caller_qn: Qualified name of the enclosing function or method.
            caller_class: Name of the enclosing class, or ``None``.
            symbol_index: Name-to-qualified-name lookup from the first pass.
            edges: Mutable list to which new CALLS edges are appended.
        """
        in_test = is_test_file(file_path)
        for node in self._walk(body_node):
            if node.type != "call":
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

        Handles three patterns:

        * ``identifier`` — plain function or constructor call (e.g. ``helper()``,
          ``Service()``).  Within a class body, the same-class method is
          preferred if the name matches.
        * ``attribute`` with ``self`` object — intra-class method call
          (``self.validate()``).
        * ``attribute`` with a class name object — explicit class call
          (``UserService.get_user()``).

        Args:
            func_node: The ``function`` child of a tree-sitter ``call`` node.
            source: Raw source bytes.
            caller_class: Name of the enclosing class, or ``None``.
            symbol_index: Name-to-qualified-name lookup.

        Returns:
            The resolved qualified name string, or ``None`` if the target
            cannot be resolved to a known intra-file symbol.
        """
        if func_node.type == "identifier":
            name = self._text(func_node, source)
            # Prefer same-class method when inside a class
            if caller_class:
                key = f"{caller_class}.{name}"
                if key in symbol_index:
                    return symbol_index[key][0]
            candidates = symbol_index.get(name, [])
            return candidates[0] if len(candidates) == 1 else None

        if func_node.type == "attribute":
            obj_node = func_node.child_by_field_name("object")
            attr_node = func_node.child_by_field_name("attribute")
            if obj_node is None or attr_node is None:
                return None
            obj = self._text(obj_node, source)
            attr = self._text(attr_node, source)

            if obj == "self" and caller_class:
                key = f"{caller_class}.{attr}"
                candidates = symbol_index.get(key, [])
                return candidates[0] if candidates else None

            # ClassName.method() or module.function()
            key = f"{obj}.{attr}"
            candidates = symbol_index.get(key, [])
            return candidates[0] if candidates else None

        return None

    def _get_raw_callee_name(self, func_node, source: bytes) -> str | None:
        """Extract the bare name of a callee without resolving to a qualified name.

        Used to capture cross-file call targets in test files so that
        :meth:`~codeindex.graph_store.GraphStore.update_covers_edges` can later
        resolve them against the full node index.

        Args:
            func_node: The ``function`` child of a tree-sitter ``call`` node.
            source: Raw source bytes.

        Returns:
            The bare callee name (e.g. ``"add"`` or ``"validate"``), or ``None``
            if no name can be extracted.
        """
        if func_node.type == "identifier":
            return self._text(func_node, source)
        if func_node.type == "attribute":
            attr_node = func_node.child_by_field_name("attribute")
            if attr_node is not None:
                return self._text(attr_node, source)
        return None

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def _get_name(self, node, source: bytes) -> str:
        """Return the identifier name of a class or function definition node.

        Args:
            node: A tree-sitter ``class_definition`` or ``function_definition`` node.
            source: Raw source bytes.

        Returns:
            The name as a string, or ``"<unknown>"`` if no ``identifier`` child
            is found.
        """
        for child in node.children:
            if child.type == "identifier":
                return self._text(child, source)
        return "<unknown>"

    def _get_signature(self, node, source: bytes) -> str:
        """Extract the signature line from a class or function definition.

        Reads up to (but not including) the first top-level colon, correctly
        handling colons that appear inside parameter default values or type
        annotations nested inside brackets.

        Args:
            node: A tree-sitter ``class_definition`` or ``function_definition`` node.
            source: Raw source bytes.

        Returns:
            The signature string without the trailing colon (e.g.
            ``"def get_user(self, user_id: int) -> User"``).
        """
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
        """Return the ``block`` child of a class or function definition node.

        Args:
            node: A tree-sitter ``class_definition`` or ``function_definition`` node.

        Returns:
            The ``block`` child node, or ``None`` if the definition has no body
            (e.g. a stub or syntax error).
        """
        for child in node.children:
            if child.type == "block":
                return child
        return None

    def _get_module_docstring(self, root, source: bytes) -> str | None:
        """Extract the module-level docstring from the root node.

        A module docstring is the first statement of the file if it is a bare
        string literal (``expression_statement`` containing a ``string``).

        Args:
            root: The tree-sitter root node of the parsed file.
            source: Raw source bytes.

        Returns:
            The docstring content with surrounding quotes removed, or ``None``
            if the module has no docstring.
        """
        for child in root.children:
            # tree-sitter ≥0.23: string appears directly in the module body
            if child.type == "string":
                return self._strip_string_quotes(self._text(child, source))
            # older tree-sitter: string wrapped in expression_statement
            if child.type == "expression_statement" and child.children:
                expr = child.children[0]
                if expr.type == "string":
                    return self._strip_string_quotes(self._text(expr, source))
            # Skip comments and blank lines; stop at any real statement
            elif child.type not in ("comment", "\n"):
                break
        return None

    def _get_docstring(self, node, source: bytes) -> str | None:
        """Extract and strip the docstring from a class or function definition.

        Compatible with both tree-sitter ≥ 0.23 (where the ``string`` node
        appears directly inside the ``block``) and older versions (where it is
        wrapped in an ``expression_statement``).

        Args:
            node: A tree-sitter ``class_definition`` or ``function_definition`` node.
            source: Raw source bytes.

        Returns:
            The docstring content with surrounding quotes removed, or ``None`` if
            the definition has no docstring.
        """
        body = self._get_body(node)
        if not body or not body.children:
            return None
        first = body.children[0]
        # tree-sitter ≥0.23: string appears directly in block
        if first.type == "string":
            return self._strip_string_quotes(self._text(first, source))
        # older tree-sitter: string wrapped in expression_statement
        if first.type == "expression_statement" and first.children:
            expr = first.children[0]
            if expr.type == "string":
                return self._strip_string_quotes(self._text(expr, source))
        return None

    @staticmethod
    def _strip_string_quotes(text: str) -> str | None:
        """Remove enclosing quote delimiters from a Python string literal.

        Tries triple-quote variants before single-quote variants to avoid
        mis-stripping.

        Args:
            text: The full string literal text including its delimiters
                (e.g. ``'\"\"\"Hello world\"\"\"'``).

        Returns:
            The inner content with leading/trailing whitespace stripped, or
            ``None`` if *text* does not match any recognised quote pattern.
        """
        for q in ('"""', "'''", '"', "'"):
            if text.startswith(q) and text.endswith(q) and len(text) >= 2 * len(q):
                return text[len(q) : -len(q)].strip()
        return None

    def _get_decorators(self, decorated_node, source: bytes) -> list[str]:
        """Collect decorator text strings from a ``decorated_definition`` node.

        Args:
            decorated_node: A tree-sitter ``decorated_definition`` node.
            source: Raw source bytes.

        Returns:
            List of decorator text strings (e.g. ``["@staticmethod", "@property"]``).
            Empty list if the node has no decorators.
        """
        return [
            self._text(child, source)
            for child in decorated_node.children
            if child.type == "decorator"
        ]

    def _get_bases(self, class_node, source: bytes) -> list[str]:
        """Extract base class names from a ``class_definition`` node.

        Handles both plain identifiers (``class Foo(Bar)``) and dotted attribute
        access (``class Foo(module.Bar)``).

        Args:
            class_node: A tree-sitter ``class_definition`` node.
            source: Raw source bytes.

        Returns:
            List of base class name strings.  Empty list for classes with no
            explicit base (i.e. implicitly inheriting from ``object``).
        """
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
            yield from PythonParser._walk(child)
