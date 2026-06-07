"""Configurable journal registry.

The set of tracked journals lives in ``config/journals.json`` so adding a journal
or feed is a config edit, not a code change. Each journal declares the canonical
``label`` shown in outputs, a stable ``key`` used for the data store
(``data/<key>/<YYYY-MM>.csv``), its publisher ``family``, and one or more RSS
``feeds``. The human-readable mirror of this file is ``Journal-RSS.md``.

A built-in default is used if the config file is absent, so the pipeline still
runs on a fresh checkout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from mat_trend.taxonomy import DEFAULT_CONFIG_DIR

JOURNALS_FILENAME = "journals.json"

# Minimal fallback used when config/journals.json is missing.
DEFAULT_JOURNALS = [
    {
        "key": "natmater",
        "label": "Nature Materials",
        "family": "Nature",
        "feeds": [{"url": "https://www.nature.com/nmat.rss", "type": "journal", "focus": "high"}],
    },
]


class RegistryError(ValueError):
    """Raised when journal registry data is invalid."""


@dataclass(frozen=True)
class Feed:
    url: str
    type: str = "journal"  # subject | journal | etoc | current | inpress
    focus: str = "mixed"  # high | mixed


@dataclass(frozen=True)
class Journal:
    key: str
    label: str
    family: str
    feeds: tuple[Feed, ...]
    frequency: str = "monthly"  # continuous | weekly | biweekly | monthly — drives poll cadence
    openalex: str | None = None  # OpenAlex source id (e.g. "S137773608")
    issn: str | None = None  # ISSN-L, used for Crossref historical backfill
    impact_factor: float | None = None  # approx JIF; journals.json is ordered by it

    @property
    def name(self) -> str:
        return self.label


@dataclass
class JournalRegistry:
    journals: list[Journal]

    @classmethod
    def from_dicts(cls, raw: list[dict]) -> "JournalRegistry":
        journals: list[Journal] = []
        for entry in raw:
            try:
                key = entry["key"]
                label = entry["label"]
                feeds_raw = entry["feeds"]
            except (KeyError, TypeError) as exc:
                raise RegistryError(f"Invalid journal entry: {entry!r}") from exc
            if not feeds_raw:
                raise RegistryError(f"Journal {key!r} must declare at least one feed")
            feeds = tuple(
                Feed(
                    url=f["url"],
                    type=f.get("type", "journal"),
                    focus=f.get("focus", "mixed"),
                )
                for f in feeds_raw
            )
            journals.append(
                Journal(
                    key=key,
                    label=label,
                    family=entry.get("family", label),
                    feeds=feeds,
                    frequency=entry.get("frequency", "monthly"),
                    openalex=entry.get("openalex"),
                    issn=entry.get("issn"),
                    impact_factor=entry.get("impact_factor"),
                )
            )
        return cls(journals=journals)

    @classmethod
    def load(cls, config_dir: Path | str = DEFAULT_CONFIG_DIR) -> "JournalRegistry":
        path = Path(config_dir) / JOURNALS_FILENAME
        if not path.exists():
            return cls.from_dicts(DEFAULT_JOURNALS)
        data = json.loads(path.read_text(encoding="utf-8"))
        journals = data.get("journals") if isinstance(data, dict) else None
        if not isinstance(journals, list):
            raise RegistryError(f"{path} must contain a 'journals' list")
        return cls.from_dicts(journals)

    @property
    def keys(self) -> list[str]:
        return [j.key for j in self.journals]

    @property
    def key_to_label(self) -> dict[str, str]:
        return {j.key: j.label for j in self.journals}

    @property
    def key_to_family(self) -> dict[str, str]:
        return {j.key: j.family for j in self.journals}

    def journal_for_key(self, key: str) -> Journal | None:
        for j in self.journals:
            if j.key == key:
                return j
        return None

    def all_feeds(self) -> list[tuple[Journal, Feed]]:
        """Flatten to ``(journal, feed)`` pairs for iteration."""
        return [(j, feed) for j in self.journals for feed in j.feeds]
