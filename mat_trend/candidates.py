"""Candidate-keyword extraction via spaCy NER.

Given a list of (lowercased) article titles, extract named entities, drop ones
already known to the taxonomy or on the noise blocklist, and keep those occurring
more than ``threshold`` times. The result feeds the ``curate-topics`` skill: each
candidate carries its count and a few example titles so the reasoning step can
decide noise vs. existing-topic vs. new-topic.

The default model is spaCy's general English pipeline ``en_core_web_lg``, which is
a reasonable fit for materials-science titles. ``load_model`` accepts any spaCy
model path or installed package name, so a domain-tuned model can be swapped in.

This is an optional extra (``pip install -e '.[curate]'``); the deterministic
ingest -> assign -> trends -> site pipeline does not require it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from spacy.language import Language

    from mat_trend.taxonomy import Taxonomy

DEFAULT_MODEL_PATH = "en_core_web_lg"
DEFAULT_THRESHOLD = 5
DEFAULT_EXAMPLES = 3
_MAX_DOC_CHARS = 5_000_000


@dataclass
class Candidate:
    """A candidate keyword awaiting AI curation."""

    keyword: str
    count: int
    examples: list[str]


def load_model(model_path: Path | str = DEFAULT_MODEL_PATH) -> "Language":
    """Load the spaCy model from a local path or an installed package name."""
    import spacy

    target = str(model_path)
    try:
        nlp = spacy.load(target)
    except (OSError, IOError) as exc:
        raise FileNotFoundError(
            f"spaCy model not found at path or as package: {target}"
        ) from exc
    nlp.max_length = max(nlp.max_length, _MAX_DOC_CHARS)
    return nlp


def extract_entities(text: str, nlp: "Language") -> list[str]:
    return [ent.text for ent in nlp(text).ents]


# Components not needed for NER — disabling them makes corpus-scale extraction
# dramatically faster.
_NER_DISABLE = ["tagger", "attribute_ruler", "lemmatizer", "parser"]


def extract_entities_batched(titles: list[str], nlp: "Language", *, batch_size: int = 1000) -> set[str]:
    """Named entities across many titles via ``nlp.pipe`` (scales to large corpora).

    Equivalent in result to running NER per title; avoids spaCy's single-doc
    ``max_length`` guard that a 60k-title blob would trip.
    """
    disable = [p for p in _NER_DISABLE if p in nlp.pipe_names]
    entities: set[str] = set()
    for doc in nlp.pipe(titles, batch_size=batch_size, disable=disable):
        entities.update(ent.text for ent in doc.ents)
    return entities


def count_occurrences(titles: list[str], keyword: str) -> int:
    return sum(1 for title in titles if keyword in title)


def _examples_for(keyword: str, titles: list[str], limit: int) -> list[str]:
    out: list[str] = []
    for title in titles:
        if keyword in title:
            out.append(title)
            if len(out) >= limit:
                break
    return out


def candidate_keywords(
    titles: list[str],
    taxonomy: "Taxonomy",
    *,
    model_path: Path | str = DEFAULT_MODEL_PATH,
    threshold: int = DEFAULT_THRESHOLD,
    examples: int = DEFAULT_EXAMPLES,
    nlp: "Language | None" = None,
) -> list[Candidate]:
    """Return candidate keywords (count > ``threshold``), most frequent first.

    ``titles`` should be lowercased so entities and substring counts are computed
    consistently with the matcher in :mod:`mat_trend.assign`.
    """
    if nlp is None:
        nlp = load_model(model_path)

    from collections import Counter, defaultdict

    known = taxonomy.known_keywords()
    blocked = taxonomy.useless_kw

    # Single pass over the corpus: document-frequency of each entity (how many
    # titles it is tagged in) + a few example titles. This is the count used for
    # curation judgement, and scales to a 60k-title corpus (the old per-entity
    # substring count was O(entities x titles)).
    doc_freq: Counter[str] = Counter()
    examples_by_kw: dict[str, list[str]] = defaultdict(list)
    disable = [p for p in _NER_DISABLE if p in nlp.pipe_names]
    for title, doc in zip(titles, nlp.pipe(titles, batch_size=1000, disable=disable)):
        for kw in {ent.text for ent in doc.ents}:
            doc_freq[kw] += 1
            if len(examples_by_kw[kw]) < examples:
                examples_by_kw[kw].append(title)

    candidates = [
        Candidate(keyword=kw, count=count, examples=examples_by_kw[kw])
        for kw, count in doc_freq.items()
        if count > threshold and kw not in known and kw not in blocked
    ]
    candidates.sort(key=lambda c: c.count, reverse=True)
    return candidates


def candidates_to_dicts(candidates: list[Candidate]) -> list[dict]:
    return [asdict(c) for c in candidates]
