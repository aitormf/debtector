"""Fixture for testing CALLS edge extraction."""


def helper() -> str:
    """A simple helper function."""
    return "ok"


def main() -> None:
    """Calls helper() — should produce a CALLS edge main→helper."""
    result = helper()
    return result


class Service:
    """A service with methods that call each other."""

    def process(self, data: str) -> str:
        """Calls self.validate() — should produce CALLS process→validate."""
        if self.validate(data):
            return self.transform(data)
        return ""

    def validate(self, data: str) -> bool:
        """Validates data."""
        return bool(data)

    def transform(self, data: str) -> str:
        """Transforms data."""
        return data.upper()


class Pipeline:
    """Uses Service — should produce CALLS edges to Service constructor."""

    def run(self, value: str) -> str:
        """Calls Service() constructor and process()."""
        svc = Service()
        return svc.process(value)
