"""Tests for the tree-sitter cyclomatic complexity helper.

Python expectations were derived by running ``radon cc -s`` on the same snippets, so the
rule set mirrors radon. JS/TS expectations follow the documented McCabe rules.
"""

from __future__ import annotations

import pytest
from debtector.parser.complexity import (
    JS_RULES,
    PYTHON_RULES,
    ComplexityRules,
    cyclomatic_complexity,
)
from tree_sitter_language_pack import get_parser


def _first(node, types: set[str]):
    """Return the first node (pre-order) whose type is in *types*."""
    if node.type in types:
        return node
    for child in node.children:
        found = _first(child, types)
        if found is not None:
            return found
    return None


def _py(src: str) -> int:
    root = get_parser("python").parse(src.encode()).root_node
    fn = _first(root, {"function_definition"})
    assert fn is not None
    return cyclomatic_complexity(fn.child_by_field_name("body"), PYTHON_RULES)


def _js(src: str) -> int:
    root = get_parser("typescript").parse(src.encode()).root_node
    fn = _first(root, {"function_declaration", "method_definition", "arrow_function"})
    assert fn is not None
    return cyclomatic_complexity(fn.child_by_field_name("body"), JS_RULES)


PY_CASES = {
    "empty": ("def f():\n    pass\n", 1),
    # radon: boolops B (7) = 1 + if + (a and b and c)=2 + (a or b)=1 + (a and b or c)=2
    "bool_ops": (
        "def f(a, b, c):\n"
        "    if a and b and c:\n        pass\n"
        "    x = a or b\n"
        "    y = a and b or c\n"
        "    return x\n",
        7,
    ),
    "if_elif_else": (
        "def f(a):\n    if a:\n        pass\n    elif a > 1:\n        pass\n"
        "    else:\n        pass\n",
        3,
    ),
    # radon: loops A (5): for, for-else, while, while-else
    "loops_with_else": (
        "def f(xs):\n"
        "    for x in xs:\n        pass\n    else:\n        pass\n"
        "    while xs:\n        break\n    else:\n        pass\n",
        5,
    ),
    # radon: tries A (4): two excepts + try-else; finally is free
    "try_except_else_finally": (
        "def f():\n    try:\n        pass\n    except ValueError:\n        pass\n"
        "    except (A, B):\n        pass\n    else:\n        pass\n    finally:\n        pass\n",
        4,
    ),
    "with_is_free": ("def f():\n    with open('f') as fh:\n        pass\n", 1),
    "ternary": ("def f(a):\n    return 1 if a else 2\n", 2),
    "assert": ("def f(a):\n    assert a, 'm'\n", 2),
    # radon: comp A (5): two `for` clauses + two `if` clauses
    "comprehension": ("def f(xs):\n    return [x for x in xs if x if x > 1 for y in x]\n", 5),
    "dict_comprehension": ("def f(xs):\n    return {x: y for x in xs for y in xs}\n", 3),
    "generator": ("def f(xs):\n    return sum(x for x in xs)\n", 2),
    # radon counts the ternary inside the lambda but not the lambda itself
    "lambda": ("def f(a):\n    g = lambda y: y if y else 0\n    return g\n", 2),
    # radon: nested A (2): the closure's own `if` does not count for the outer function
    "nested_function_excluded": (
        "def f(a):\n    def inner(b):\n        if b:\n            pass\n"
        "    if a:\n        pass\n    return inner\n",
        2,
    ),
    # radon: matcher A (3): three cases minus the wildcard
    "match": (
        "def f(a):\n    match a:\n        case 1:\n            pass\n"
        "        case 2 | 3:\n            pass\n        case _:\n            pass\n",
        3,
    ),
    "match_guard_is_free": (
        "def f(a):\n    match a:\n        case 1 if a:\n            pass\n"
        "        case _:\n            pass\n",
        2,
    ),
    "not_is_free": ("def f(a, b):\n    return not a and b\n", 2),
    "chained_comparison_is_free": ("def f(a, b):\n    return a < b < 3\n", 1),
    # radon: af A (2): `async for` counts, `async with` and `await` do not
    "async": (
        "async def f(a):\n    async for x in a:\n        pass\n"
        "    async with a:\n        pass\n    await a\n",
        2,
    ),
    "decorator_and_defaults_ignored": (
        "@d(a if a else b)\ndef f(x=1 if True else 2):\n    pass\n",
        1,
    ),
}


@pytest.mark.parametrize(("src", "expected"), PY_CASES.values(), ids=PY_CASES.keys())
def test_python_complexity(src: str, expected: int) -> None:
    assert _py(src) == expected


JS_CASES = {
    "empty": ("function f() {}", 1),
    "if_else_if": ("function f(a) { if (a) {} else if (a > 1) {} else {} }", 3),
    "loops": (
        "function f(xs) { for (let i = 0; i < 1; i++) {} for (const k in xs) {} "
        "for (const v of xs) {} while (xs) {} do {} while (xs); }",
        6,
    ),
    "try_catch_finally": ("function f() { try {} catch (e) {} finally {} }", 2),
    "switch_default_is_free": (
        "function f(a) { switch (a) { case 1: break; case 2: break; default: break; } }",
        3,
    ),
    "ternary": ("function f(a) { return a ? 1 : 2; }", 2),
    "logical_and_or": ("function f(a, b, c) { return (a && b) || c; }", 3),
    "nullish": ("function f(a, b) { return a ?? b; }", 2),
    "logical_assignment": ("function f(a, b) { a ||= b; a &&= b; a ??= b; }", 4),
    "comparison_is_free": ("function f(a, b) { return a === b || a !== 1 ? 1 : 2; }", 3),
    # nested callbacks are not graph nodes, so they count toward the enclosing function
    "callback_folded": ("function f(xs) { return xs.map(x => x ? 1 : 2); }", 2),
    "arrow_expression_body": ("const g = (a) => a && a.b;", 2),
    "ts_method": ("class A { m(a: number): number { return a > 0 ? 1 : 2; } }", 2),
}


@pytest.mark.parametrize(("src", "expected"), JS_CASES.values(), ids=JS_CASES.keys())
def test_js_complexity(src: str, expected: int) -> None:
    assert _js(src) == expected


def test_missing_body_is_one() -> None:
    assert cyclomatic_complexity(None, PYTHON_RULES) == 1


def test_rules_are_declarative() -> None:
    assert isinstance(PYTHON_RULES, ComplexityRules)
    assert isinstance(JS_RULES, ComplexityRules)
