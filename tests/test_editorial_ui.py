"""Guard the shared UI layer without changing published data semantics."""
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_editorial_layer_loads_after_reader_styles_and_is_versioned():
    head = (ROOT / 'docs/_includes/head-custom.html').read_text()
    assert head.index('editorial-ui.css') > head.index('pwa-reader.css')
    assert "'/assets/css/editorial-ui.css' | relative_url }}?v={{ site.asset_version }}" in head


def test_shared_reading_size_covers_lists_details_and_backgrounds():
    css = (ROOT / 'docs/assets/css/editorial-ui.css').read_text()
    for selector in ['.event-brief-block p', '.entity-feed-overview p',
                     '.entity-background p', '.event-current-state p',
                     '.event-update-change', '.story-more-content > section p',
                     '.weekly-brief-grid .event-brief-latest p']:
        assert selector in css
    assert 'font-size: var(--reading-size)' in css
    assert 'min-width: 1101px' in css
    assert '.section-index-body' in css


def test_production_templates_keep_evidence_and_details():
    archive = (ROOT / 'docs/_includes/archive-index.html').read_text()
    weekly = (ROOT / 'docs/_includes/weekly-edition.html').read_text()
    for field in ['row.background_zh', 'row.discussion_zh', 'row.reference_links',
                  'row.recent_items', 'row.event_id']:
        assert field in archive
    assert 'why_it_matters' in weekly
    assert 'item.evidence' in weekly
    assert 'section-index-body' in archive and 'section-index-body' in weekly
    assert 'entity_background | escape' in archive
