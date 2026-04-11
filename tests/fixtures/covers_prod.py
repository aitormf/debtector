"""Production module fixture for COVERS edge tests."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a - b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


class Calculator:
    """Simple calculator."""

    def compute(self, a: int, b: int) -> int:
        """Delegate to add."""
        return add(a, b)
