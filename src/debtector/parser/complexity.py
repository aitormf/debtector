"""Cyclomatic complexity (McCabe) computed on tree-sitter syntax trees.

The helper is parser-agnostic: a :class:`ComplexityRules` instance tells it which node
types are decision points, which nodes start a separate scope (and are therefore not
counted for the enclosing function) and, optionally, how to weigh nodes that need more
than a type check.

Rules, per function or method (every function starts at 1):

Python (mirrors ``radon cc``, so values can be cross-checked with it)
    * +1 for each ``if``, ``elif``, ``for``, ``while``, ``except`` clause, ``assert``,
      conditional expression (ternary) and comprehension ``for`` / ``if`` clause.
    * +1 for the ``else`` of a ``for``, ``while`` or ``try``.
    * +1 for each boolean operator (``a and b and c`` is +2, ``a and b or c`` is +2).
    * +1 for each ``case`` of a ``match``, minus one if there is a wildcard or capture
      ``case`` (``case _`` / ``case name``); guards are free.
    * Free: ``with``, ``finally``, ``not``, comparisons, ``await``, ``lambda`` itself
      (but its body is counted).
    * Only the function body counts: decorators, default values and annotations do not.
    * Nested functions and classes are separate scopes and are not added to the
      enclosing function's ``complexity`` (so it stays comparable with radon). Since
      they are not graph nodes, :func:`nested_complexity` sums them (recursively) so
      the parser can store it as ``nested_complexity`` and file totals do not lose it.

JavaScript / TypeScript
    * +1 for each ``if`` (so ``else if`` too), ``for``, ``for...in``, ``for...of``,
      ``while``, ``do``, ``catch``, ``case`` (``default`` is free) and ternary.
    * +1 for each ``&&``, ``||`` and ``??`` (and ``&&=``, ``||=``, ``??=``).
    * Nested functions and arrow callbacks are not nodes of the graph, so their
      decision points are folded into the enclosing function instead of being lost.
"""

from __future__ import annotations

import keyword
from collections.abc import Callable
from dataclasses import dataclass

from tree_sitter import Node


@dataclass(frozen=True)
class ComplexityRules:
    """Language-specific description of what counts as a decision point.

    Attributes:
        decision_nodes: Node types that add 1 each.
        boundary_nodes: Node types that start a separate scope: neither the node nor
            its subtree is counted.
        function_nodes: Boundary node types that are functions, whose own complexity is
            reported by :func:`nested_complexity`.
        weigh: Optional hook returning the extra complexity of a node (``0`` if none).
    """

    decision_nodes: frozenset[str]
    boundary_nodes: frozenset[str] = frozenset()
    function_nodes: frozenset[str] = frozenset()
    weigh: Callable[[Node], int] | None = None


def cyclomatic_complexity(body: Node | None, rules: ComplexityRules) -> int:
    """Compute the cyclomatic complexity of a function body.

    Args:
        body: The tree-sitter node holding the function body (a block, or an expression
            for arrow functions). ``None`` means no body.
        rules: The language rules.

    Returns:
        ``1`` plus the number of decision points found in *body*.
    """
    if body is None:
        return 1
    total = 1
    stack = [body]
    while stack:
        node = stack.pop()
        if node is not body and node.type in rules.boundary_nodes:
            continue
        if node.type in rules.decision_nodes:
            total += 1
        if rules.weigh is not None:
            total += rules.weigh(node)
        stack.extend(node.children)
    return total


def nested_complexity(body: Node | None, rules: ComplexityRules) -> int:
    """Sum the complexity of the functions nested inside *body*, recursively.

    The whole subtree is searched (conditional or looped closures, methods of local
    classes); only the nested functions' own decision points count, not those of
    local class bodies.

    Args:
        body: The enclosing function's body node (``None`` means no body).
        rules: The language rules.

    Returns:
        The summed complexity of every nested function (each including its own
        nested functions), ``0`` if there are none or the language has no boundaries.
    """
    if body is None:
        return 0
    total = 0
    stack = list(body.children)
    while stack:
        node = stack.pop()
        if node.type in rules.function_nodes:
            inner = node.child_by_field_name("body")
            total += cyclomatic_complexity(inner, rules) + nested_complexity(inner, rules)
        else:
            # Any other node (blocks of if/for/try/with/match, local classes...) may hold
            # nested functions. A nested function is not descended into here: its own
            # nested functions are added by the recursive call, so each counts once.
            stack.extend(node.children)
    return total


# ──────────────────────────────────────────────
# Python
# ──────────────────────────────────────────────


def _is_wildcard_case(case: Node) -> bool:
    """Return whether a ``case_clause`` is ``case _`` or a bare capture (``case name``)."""
    patterns = [c for c in case.children if c.type == "case_pattern"]
    if len(patterns) != 1 or patterns[0].text is None:
        return False
    text = patterns[0].text.decode("utf-8", errors="replace")
    return text.isidentifier() and not keyword.iskeyword(text)


def _python_weigh(node: Node) -> int:
    parent_type = node.parent.type if node.parent is not None else ""
    if node.type == "else_clause":
        return int(parent_type in ("for_statement", "while_statement", "try_statement"))
    if node.type == "if_clause":
        return int(parent_type != "case_clause")  # a match guard is not a decision point
    if node.type == "match_statement":
        body = node.child_by_field_name("body")
        cases = [c for c in body.children if c.type == "case_clause"] if body else []
        wildcard = any(_is_wildcard_case(c) for c in cases)
        return max(0, len(cases) - int(wildcard))
    return 0


PYTHON_RULES = ComplexityRules(
    decision_nodes=frozenset(
        {
            "if_statement",
            "elif_clause",
            "for_statement",
            "while_statement",
            "except_clause",
            "assert_statement",
            "conditional_expression",
            "boolean_operator",
            "for_in_clause",
        }
    ),
    boundary_nodes=frozenset({"function_definition", "class_definition", "decorated_definition"}),
    function_nodes=frozenset({"function_definition"}),
    weigh=_python_weigh,
)


# ──────────────────────────────────────────────
# JavaScript / TypeScript
# ──────────────────────────────────────────────

_JS_LOGICAL_OPERATORS = frozenset({"&&", "||", "??"})
_JS_LOGICAL_ASSIGNMENTS = frozenset({"&&=", "||=", "??="})


def _js_weigh(node: Node) -> int:
    if node.type == "binary_expression":
        operator = node.child_by_field_name("operator")
        return int(operator is not None and operator.type in _JS_LOGICAL_OPERATORS)
    if node.type == "augmented_assignment_expression":
        operator = node.child_by_field_name("operator")
        return int(operator is not None and operator.type in _JS_LOGICAL_ASSIGNMENTS)
    return 0


JS_RULES = ComplexityRules(
    decision_nodes=frozenset(
        {
            "if_statement",
            "for_statement",
            "for_in_statement",
            "while_statement",
            "do_statement",
            "catch_clause",
            "switch_case",
            "ternary_expression",
        }
    ),
    weigh=_js_weigh,
)
