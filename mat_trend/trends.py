"""Topic-frequency trends: top / emerging / fading per journal (or family) period.

Adapted from AI-trend's ``trends.py``. The difference is identity: AI-trend keys on
*(conference, year)*; Mater-trend keys on *(group, period)* where ``group`` is a
journal (default) or its publisher family, and ``period`` is a time bucket (month
by default, or quarter).

Definitions, unchanged from AI-trend:

* **count** — number of articles carrying a topic (a paper may carry several; the
  ``topic`` column is ``;``-joined).
* **top** — the ``top_n`` topics by current-period count.
* **change ratio** — ``(current - previous) / previous`` versus the same group's
  previous period. A brand-new topic (prev 0, cur > 0) has an infinite ratio; a
  topic absent both periods (0 -> 0) is NaN and excluded.
* **emerging / fading** — the ``top_n`` topics by highest / lowest change ratio.

Group/period identity comes from the **file location** (folder = journal key,
filename stem = month), via the registry — not from in-file columns.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from mat_trend.ingest import DEFAULT_DATA_DIR

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mat_trend.taxonomy import Taxonomy

DEFAULT_TOP_N = 5
# A topic needs at least this many articles in the *previous* period to be eligible
# for emerging/fading (excludes the undefined 0->n infinite-ratio case).
DEFAULT_MIN_PREV = 1
# A topic needs at least this many articles in the *current* period to count as
# emerging (real volume, not a couple of keyword coincidences). Tunable per the
# feed volume; biology month buckets are smaller than a conference dump, so the
# default is lower than AI-trend's.
DEFAULT_MIN_COUNT = 3
TOPICS_GLOB = "*.csv_topics.csv"
_MONTH = re.compile(r"^\d{4}-\d{2}$")

GROUP_JOURNAL = "journal"
GROUP_FAMILY = "family"
BUCKET_MONTH = "month"
BUCKET_QUARTER = "quarter"
BUCKET_YEAR = "year"
BUCKETS = (BUCKET_YEAR, BUCKET_QUARTER, BUCKET_MONTH)


@dataclass
class Trend:
    """Trend lists for one group-period (relative to the previous period)."""

    group: str  # journal label or family name
    period: str  # e.g. "2025-06" or "2025-Q2"
    previous_period: str | None
    top: list[str] = field(default_factory=list)
    emerging: list[str] = field(default_factory=list)
    fading: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


def month_of(path: Path) -> str | None:
    """``2025-06.csv_topics.csv`` -> ``2025-06`` (None if not a month-stem file)."""
    stem = path.name.split(".csv", 1)[0]
    return stem if _MONTH.match(stem) else None


def bucket_for(month: str, bucket: str) -> str:
    """Map a ``YYYY-MM`` month to its time bucket (``year`` / ``quarter`` / ``month``)."""
    year, mon = month.split("-")
    if bucket == BUCKET_YEAR:
        return year
    if bucket == BUCKET_QUARTER:
        return f"{year}-Q{(int(mon) - 1) // 3 + 1}"
    return month


def topic_counts(topics: Iterable[str], taxonomy: "Taxonomy") -> dict[str, int]:
    """Count papers per topic, initialising every taxonomy topic to 0."""
    counts = {topic: 0 for topic in taxonomy.topics}
    for cell in topics:
        for topic in str(cell).split(";"):
            if topic == "" or topic == "nan":
                continue
            counts[topic] = counts.get(topic, 0) + 1
    return counts


def count_file(path: Path | str, taxonomy: "Taxonomy") -> dict[str, int]:
    import pandas as pd

    df = pd.read_csv(path)
    if "topic" not in df.columns:
        raise ValueError(f"{path} has no 'topic' column")
    return topic_counts(df["topic"], taxonomy)


def _merge_counts(dicts: Iterable[dict[str, int]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in dicts:
        for topic, count in d.items():
            out[topic] = out.get(topic, 0) + count
    return out


def _change_ratio(current: int, previous: int) -> float:
    if previous == 0:
        return math.inf if current > 0 else math.nan
    return (current - previous) / previous


def compute_trends(
    group: str,
    period: str,
    current: dict[str, int],
    previous: dict[str, int] | None,
    *,
    previous_period: str | None = None,
    top_n: int = DEFAULT_TOP_N,
    min_prev: int = DEFAULT_MIN_PREV,
    min_count: int = DEFAULT_MIN_COUNT,
) -> Trend:
    """Build the top/emerging/fading lists for one group-period."""
    ordered = list(current)  # taxonomy order -> stable tie-breaking
    top = sorted(ordered, key=lambda t: current[t], reverse=True)[:top_n]

    emerging: list[str] = []
    fading: list[str] = []
    if previous is not None:
        with_baseline = [t for t in ordered if previous.get(t, 0) >= min_prev]
        ratios = {t: _change_ratio(current[t], previous.get(t, 0)) for t in with_baseline}
        emerging_eligible = [t for t in with_baseline if current[t] >= min_count]
        emerging = sorted(emerging_eligible, key=lambda t: ratios[t], reverse=True)[:top_n]
        fading = sorted(with_baseline, key=lambda t: ratios[t])[:top_n]

    return Trend(
        group=group,
        period=period,
        previous_period=previous_period if previous is not None else None,
        top=top,
        emerging=emerging,
        fading=fading,
        counts=current,
    )


def discover_groups(
    taxonomy: "Taxonomy",
    data_dir: Path | str = DEFAULT_DATA_DIR,
    *,
    group_by: str = GROUP_JOURNAL,
    bucket: str = BUCKET_MONTH,
    key_to_label: dict[str, str] | None = None,
    key_to_family: dict[str, str] | None = None,
) -> dict[str, dict[str, dict[str, int]]]:
    """Index ``{group: {period: merged_counts}}`` from ``data/<key>/<month>.csv_topics.csv``."""
    if key_to_label is None or key_to_family is None:
        from mat_trend.registry import JournalRegistry

        reg = JournalRegistry.load()
        key_to_label = key_to_label or reg.key_to_label
        key_to_family = key_to_family or reg.key_to_family

    data_dir = Path(data_dir)
    # group -> period -> list of monthly count dicts (merged later)
    staged: dict[str, dict[str, list[dict[str, int]]]] = {}
    if not data_dir.exists():
        return {}

    for key_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        key = key_dir.name
        label = key_to_label.get(key)
        if label is None:
            continue
        group = key_to_family.get(key, label) if group_by == GROUP_FAMILY else label
        for path in sorted(key_dir.glob(TOPICS_GLOB)):
            month = month_of(path)
            if month is None:
                continue
            period = bucket_for(month, bucket)
            counts = count_file(path, taxonomy)
            staged.setdefault(group, {}).setdefault(period, []).append(counts)

    return {
        group: {period: _merge_counts(chunks) for period, chunks in periods.items()}
        for group, periods in staged.items()
    }


def compute_all_trends(
    taxonomy: "Taxonomy",
    data_dir: Path | str = DEFAULT_DATA_DIR,
    *,
    group_by: str = GROUP_JOURNAL,
    bucket: str = BUCKET_MONTH,
    top_n: int = DEFAULT_TOP_N,
    min_prev: int = DEFAULT_MIN_PREV,
    min_count: int = DEFAULT_MIN_COUNT,
    key_to_label: dict[str, str] | None = None,
    key_to_family: dict[str, str] | None = None,
) -> list[Trend]:
    """Compute trends for every group-period, comparing to its previous period.

    ``key_to_label``/``key_to_family`` resolve the data-store folder names; pass the
    maps from the active registry so trends honour the ``--config`` in use. When
    omitted, :func:`discover_groups` falls back to the committed registry.
    """
    index = discover_groups(
        taxonomy, data_dir, group_by=group_by, bucket=bucket,
        key_to_label=key_to_label, key_to_family=key_to_family,
    )
    results: list[Trend] = []
    for group in sorted(index):
        periods = index[group]
        ordered_periods = sorted(periods)
        for i, period in enumerate(ordered_periods):
            prev_period = ordered_periods[i - 1] if i > 0 else None
            previous = periods.get(prev_period) if prev_period is not None else None
            results.append(
                compute_trends(
                    group,
                    period,
                    periods[period],
                    previous,
                    previous_period=prev_period,
                    top_n=top_n,
                    min_prev=min_prev,
                    min_count=min_count,
                )
            )
    return results


def _quote_topics(topics: list[str]) -> str:
    return ", ".join(f"'{t}'" for t in topics)


def render_markdown(trends: list[Trend]) -> str:
    """Render trend tables, newest period first."""
    lines: list[str] = []
    by_period: dict[str, list[Trend]] = {}
    for trend in trends:
        by_period.setdefault(trend.period, []).append(trend)

    for period in sorted(by_period, reverse=True):
        lines.append(f"# {period}\n")
        for trend in sorted(by_period[period], key=lambda t: t.group):
            lines.append(f"## {period} — {trend.group}")
            lines.append("| **Type**            | Topics |")
            lines.append("|---------------------|--------|")
            lines.append(f"| **Top topics**      | {_quote_topics(trend.top)} |")
            if trend.emerging:
                lines.append(f"| **Emerging topics** | {_quote_topics(trend.emerging)} |")
            if trend.fading:
                lines.append(f"| **Fading topics**   | {_quote_topics(trend.fading)} |")
            lines.append("")
    return "\n".join(lines)


def trend_to_dict(trend: Trend, *, include_counts: bool = False) -> dict:
    data = {
        "group": trend.group,
        "period": trend.period,
        "previous_period": trend.previous_period,
        "top": trend.top,
        "emerging": trend.emerging,
        "fading": trend.fading,
    }
    if include_counts:
        data["counts"] = {t: c for t, c in trend.counts.items() if c > 0}
    return data
