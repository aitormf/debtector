"""Python fixture for parser edge cases.

Covers patterns not present in sample.py:
- aliased imports  (import X as Y)
- bare relative import (from . import X) — returns None in _parse_from_module
- dotted base class (class Foo(module.Bar)) — arg.type == "attribute"
- class with no docstring
"""

import os as opsys  # noqa: F401   aliased_import → _parse_module_name lines 147-150
import sys as system  # noqa: F401  second aliased import

from . import helpers  # noqa: F401  bare relative import → _parse_from_module returns None


class Base:
    """A base class with a docstring."""

    pass


class NoDocs:
    x: int = 0  # no docstring — _get_docstring returns None (line 571)


class Extended(os.PathLike):  # noqa: F821  dotted base → arg.type == "attribute" (line 641)
    """Extends a dotted base class."""

    def __fspath__(self) -> str:
        return ""
