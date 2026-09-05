"""Safety contracts for Liquid templates consuming source/AI text."""
import re
from pathlib import Path


def test_archive_index_escapes_every_dynamic_output():
    template = Path("docs/_includes/archive-index.html").read_text()
    expressions = re.findall(r"\{\{(.*?)\}\}", template, re.S)
    assert expressions
    assert all(re.search(r"\|\s*escape\b", item) for item in expressions)


def test_event_references_use_protocol_validating_include():
    template = Path("docs/_includes/archive-index.html").read_text()
    assert 'href="{{ reference.url' not in template
    assert template.count('include external-reference.html') == 2
    reference = Path("docs/_includes/external-reference.html").read_text()
    assert "reference_scheme == 'https://'" in reference
    assert "reference_http == 'http://'" in reference
    assert '{{ reference_url | escape }}' in reference
    assert '{{ include.title | escape }}' in reference
