"""Curation decision parsing and application (pure, no spaCy/LLM)."""

import pytest

from mat_trend.curate_io import DecisionError, apply_decision, parse_decision
from mat_trend.taxonomy import Taxonomy


def _tax():
    return Taxonomy(topic2keywords={"batteries & energy storage": ["battery"]}, useless_kw=set())


def test_parse_rejects_missing_decisions():
    with pytest.raises(DecisionError):
        parse_decision({})


def test_parse_rejects_unknown_action():
    with pytest.raises(DecisionError):
        parse_decision({"decisions": [{"keyword": "x", "action": "bogus"}]})


def test_existing_requires_known_topic():
    decisions = parse_decision({"decisions": [{"keyword": "anode", "action": "existing", "topic": "nope"}]})
    with pytest.raises(DecisionError):
        apply_decision(_tax(), decisions)


def test_apply_routes_each_action():
    raw = {"decisions": [
        {"keyword": "anode", "action": "existing", "topic": "batteries & energy storage"},
        {"keyword": "mxene", "action": "new", "topic": "2D materials"},
        {"keyword": "method", "action": "noise"},
        {"keyword": "weird thing", "action": "other"},
    ]}
    result = apply_decision(_tax(), parse_decision(raw))
    assert "anode" in result.taxonomy.topic2keywords["batteries & energy storage"]
    assert "2D materials" in result.taxonomy.topic2keywords
    assert "method" in result.taxonomy.useless_kw
    assert result.other_keywords == ["weird thing"]
    assert result.summary == {"existing": 1, "new": 1, "noise": 1, "other": 1}


def test_apply_does_not_mutate_input():
    tax = _tax()
    apply_decision(tax, parse_decision({"decisions": [{"keyword": "method", "action": "noise"}]}))
    assert tax.useless_kw == set()
