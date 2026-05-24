"""Tests for docs/audit-schema.md — stable JSON contract documentation.

Gherkin contract:

    Given un consumidor externo lee docs/audit-schema.md
    When busca la semántica del campo 'health_score'
    Then encuentra definición, rango 0-100 y ejemplo JSON válido
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

SCHEMA_DOC = Path(__file__).resolve().parents[2] / "docs" / "audit-schema.md"


@pytest.fixture(scope="module")
def schema_doc_text() -> str:
    assert SCHEMA_DOC.exists(), f"Missing contract doc: {SCHEMA_DOC}"
    return SCHEMA_DOC.read_text(encoding="utf-8")


def test_health_score_has_definition(schema_doc_text: str) -> None:
    """The doc must define the semantics of 'health_score' (not just mention it)."""
    assert "health_score" in schema_doc_text, "field name not present"
    assert re.search(
        r"`health_score`.*?(score|health|aggregate)", schema_doc_text, re.IGNORECASE
    ), "no semantic definition near `health_score`"


def test_health_score_range_documented(schema_doc_text: str) -> None:
    """The 0-100 range must be explicitly documented for health_score."""
    range_patterns = [
        r"\[\s*0\s*,\s*100\s*\]",
        r"0\s*-\s*100",
        r"0\s*to\s*100",
    ]
    assert any(re.search(p, schema_doc_text) for p in range_patterns), (
        "health_score range [0, 100] not documented"
    )


def test_example_payload_is_valid_json_with_health_score(schema_doc_text: str) -> None:
    """The example JSON payload must parse and contain a health_score in [0, 100]."""
    json_blocks = re.findall(r"```json\s*(.*?)```", schema_doc_text, re.DOTALL)
    assert json_blocks, "no ```json fenced examples found"

    parsed_with_health_score = []
    for block in json_blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "summary" in payload:
            summary = payload["summary"]
            if isinstance(summary, dict) and "health_score" in summary:
                parsed_with_health_score.append(payload)

    assert parsed_with_health_score, "no valid JSON example containing summary.health_score"

    for payload in parsed_with_health_score:
        score = payload["summary"]["health_score"]
        assert isinstance(score, int), f"health_score must be int, got {type(score)}"
        assert 0 <= score <= 100, f"health_score {score} out of [0, 100]"
