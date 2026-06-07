"""Deterministic topic assignment by substring matching.

Ported from AI-trend's ``assign.py``. The matching contract:

* The search text is ``f"{title_lower} {abstract_lower}"`` — title and abstract are
  lowercased independently; a missing abstract contributes an empty string.
* A keyword matches as a plain substring of that (already-lowercased) text, so
  taxonomy keywords must be written lowercase to ever match.
* A paper receives every topic with at least one matching keyword, joined by ``;``
  in taxonomy (insertion) order.

The step is pure and reproducible: same CSV + same taxonomy -> identical labels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

    from mat_trend.taxonomy import Taxonomy

TOPIC_COLUMN = "topic"
TITLE_COLUMN = "title"
ABSTRACT_COLUMN = "abstract"


def match_topics(text: str, topic2keywords: dict[str, list[str]]) -> list[str]:
    """Return topics whose keywords appear as substrings of ``text`` (as given)."""
    matched: list[str] = []
    for topic, keywords in topic2keywords.items():
        for keyword in keywords:
            if keyword in text:
                matched.append(topic)
                break
    return matched


def build_search_text(title: object, abstract: object) -> str:
    """Lowercased ``"{title} {abstract}"``; a missing abstract contributes ""."""
    title_part = title.lower() if isinstance(title, str) else str(title or "").lower()
    abstract_part = abstract.lower() if isinstance(abstract, str) else ""
    return f"{title_part} {abstract_part}"


def topics_for_paper(title: object, abstract: object, taxonomy: "Taxonomy") -> str:
    text = build_search_text(title, abstract)
    return ";".join(match_topics(text, taxonomy.topic2keywords))


def assign_dataframe(df: "pd.DataFrame", taxonomy: "Taxonomy") -> "pd.DataFrame":
    """Return a copy of ``df`` with a ``topic`` column appended."""
    for column in (TITLE_COLUMN, ABSTRACT_COLUMN):
        if column not in df.columns:
            raise ValueError(
                f"Input is missing required column {column!r}; got {list(df.columns)}"
            )
    result = df.copy()
    result[TOPIC_COLUMN] = [
        topics_for_paper(title, abstract, taxonomy)
        for title, abstract in zip(df[TITLE_COLUMN], df[ABSTRACT_COLUMN])
    ]
    return result


def assign_csv(in_path: str, out_path: str, taxonomy: "Taxonomy") -> "pd.DataFrame":
    """Read a papers CSV, assign topics, and write ``<out_path>``."""
    import pandas as pd

    df = pd.read_csv(in_path)
    result = assign_dataframe(df, taxonomy)
    result.to_csv(out_path, index=False)
    return result
