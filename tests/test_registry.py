"""Journal registry loads from journals.json and flattens feeds."""

import json

import pytest

from mat_trend.registry import JournalRegistry, RegistryError


def _write(config_dir, journals):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "journals.json").write_text(json.dumps({"journals": journals}), encoding="utf-8")


def test_load_parses_journals_and_feeds(tmp_path):
    _write(tmp_path, [
        {"key": "cell", "label": "Cell", "family": "Cell Press",
         "feeds": [{"url": "https://x/cell.rss", "type": "current", "focus": "high"}]},
    ])
    reg = JournalRegistry.load(tmp_path)
    assert reg.keys == ["cell"]
    assert reg.key_to_label == {"cell": "Cell"}
    assert reg.key_to_family == {"cell": "Cell Press"}
    j = reg.journal_for_key("cell")
    assert j.feeds[0].url == "https://x/cell.rss"
    assert j.feeds[0].type == "current"


def test_all_feeds_flattens_multi_feed_journals(tmp_path):
    _write(tmp_path, [
        {"key": "nature", "label": "Nature", "family": "Nature",
         "feeds": [{"url": "https://x/a.rss"}, {"url": "https://x/b.rss"}]},
    ])
    reg = JournalRegistry.load(tmp_path)
    assert len(reg.all_feeds()) == 2


def test_missing_feeds_is_an_error(tmp_path):
    _write(tmp_path, [{"key": "x", "label": "X", "family": "F", "feeds": []}])
    with pytest.raises(RegistryError):
        JournalRegistry.load(tmp_path)


def test_real_config_is_loadable():
    # the committed config/journals.json must parse and cover the core publisher families
    reg = JournalRegistry.load()
    families = {j.family for j in reg.journals}
    assert {"Nature", "Science", "Cell Press", "Wiley", "ACS", "RSC", "Elsevier"} <= families
