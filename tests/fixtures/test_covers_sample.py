"""Test file fixture for COVERS edge tests.

This file is intentionally named test_*.py so that is_test_file() detects it
as a test file and the parser emits unresolved CALLS edges for cross-file calls.
The undefined names (add, subtract, Calculator) are intentional — they simulate
cross-file imports that exist in covers_prod.py.
"""
# ruff: noqa: F821


def test_add() -> None:
    """Test the add function."""
    result = add(1, 2)
    assert result == 3


def test_subtract() -> None:
    """Test the subtract function."""
    result = subtract(5, 3)
    assert result == 2


class TestCalculator:
    """Test suite for Calculator."""

    def test_compute(self) -> None:
        """Test Calculator.compute."""
        calc = Calculator()
        assert calc.compute(1, 2) == 3
