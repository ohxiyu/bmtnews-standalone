import logging
from pathlib import Path

import pytest

from src.ai.topic_dedup import DedupResponseError, validate_duplicates, response_shape
from test_ai_economy import Client, compare, stories


@pytest.mark.parametrize("payload,code", [
    (None, "not_object_or_invalid_json"),
    ({"duplicates": None}, "duplicates_not_list"),
    ({"duplicates": ["SECRET"]}, "group_not_list"),
    ({"duplicates": [[0]]}, "group_too_short"),
    ({"duplicates": [[False, 1]]}, "index_not_integer"),
    ({"duplicates": [[0, 9]]}, "index_out_of_range"),
    ({"duplicates": [[0, 0]]}, "repeated_index"),
])
def test_precise_schema_codes(payload, code):
    with pytest.raises(DedupResponseError) as exc:
        validate_duplicates(payload, 2)
    assert exc.value.code == code
    assert "SECRET" not in str(exc.value)


def test_logs_only_safe_context(caplog):
    items = stories(2)
    items[0].title = "SECRET article title"
    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError):
        compare(Client('{"duplicates": [[0,0]], "extra":"SECRET"}'), items)
    assert "repeated_index" in caplog.text
    assert '"batch_size": 2' in caplog.text
    assert '"attempt": 2' in caplog.text
    assert "SECRET" not in caplog.text


def test_shape_reports_only_types_and_counts():
    shape = response_shape([["SECRET", 1], "SECRET", {"SECRET": "SECRET"}])
    assert shape == {"root": "array", "length": 3,
                     "element_types": ["array", "object", "string"], "group_sizes": [2]}
    assert "SECRET" not in str(shape)


def test_diagnostic_has_no_publish_credentials_or_write_permissions():
    text = (Path(__file__).parents[1] / ".github/workflows/daily-summary.yml").read_text()
    job = text.split("  dedup-diagnostic:")[1].split("  daily-summary:")[0]
    assert "contents: read" in job
    assert "refs/heads/agent/*" in job
    assert "cache/save" not in job
    assert "TELEGRAM" not in job and "X_ACCESS" not in job
    assert "${{ !inputs.diagnostic_only }}" in text
