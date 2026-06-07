"""Candidate extraction logic (single-pass DF + examples), using a fake NLP."""

import types

from mat_trend.candidates import candidate_keywords
from mat_trend.taxonomy import Taxonomy


class _Ent:
    def __init__(self, text): self.text = text


class _Doc:
    def __init__(self, texts): self.ents = [_Ent(t) for t in texts]


class _FakeNLP:
    """Minimal stand-in for a spaCy pipeline: maps each title to preset entities."""
    pipe_names: list = []

    def __init__(self, mapping): self._m = mapping

    def pipe(self, titles, batch_size=1000, disable=None):
        for t in titles:
            yield _Doc(self._m.get(t, []))


def test_candidate_keywords_counts_doc_frequency_and_filters():
    titles = [
        "crispr screen one", "crispr screen two", "crispr screen three",
        "spatial omics atlas", "spatial omics study", "approach paper",
    ]
    nlp = _FakeNLP({
        "crispr screen one": ["crispr", "screen"],
        "crispr screen two": ["crispr", "screen"],
        "crispr screen three": ["crispr"],
        "spatial omics atlas": ["spatial omics"],
        "spatial omics study": ["spatial omics"],
        "approach paper": ["approach"],
    })
    # 'crispr' already known; 'approach' is noise; threshold=1 keeps DF>1
    tax = Taxonomy(topic2keywords={"genome editing": ["crispr"]}, useless_kw={"approach"})
    out = candidate_keywords(titles, tax, threshold=1, examples=2, nlp=nlp)
    names = [c.keyword for c in out]
    assert "crispr" not in names      # known -> excluded
    assert "approach" not in names    # blocklisted -> excluded
    assert "screen" in names          # DF 2 > 1
    assert "spatial omics" in names   # DF 2 > 1
    top = out[0]
    assert top.count >= 2 and len(top.examples) <= 2
