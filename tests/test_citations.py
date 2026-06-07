"""Citation tracking policy: snapshot on addition + monthly within 3 months, max 3.

Also covers the multi-source fetchers (Semantic Scholar batch, OpenAlex single-work)
and the parallel merge-by-max orchestration, using fake HTTP sessions.
"""

import datetime

from mat_trend import citations
from mat_trend.citations import citation_delta, is_due, latest_count, record_snapshot

TODAY = datetime.date(2026, 6, 15)
NO_SLEEP = lambda *_: None  # noqa: E731 — silence throttle in tests


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _S2Session:
    """Echoes citationCount for known DOIs (upper-cased, to test normalisation),
    returns ``null`` for unknown ids — exactly like the real batch endpoint."""

    def __init__(self, mapping):
        self.mapping = mapping

    def post(self, url, params=None, json=None, headers=None, timeout=None):
        out = []
        for ident in json["ids"]:
            doi = ident.split("DOI:", 1)[1]
            out.append({"externalIds": {"DOI": doi.upper()}, "citationCount": self.mapping[doi]}
                       if doi in self.mapping else None)
        return _Resp(out)


class _OASession:
    """Single-work endpoint: maps the DOI in the URL to a cited_by_count, or a status."""

    def __init__(self, mapping, status=None):
        self.mapping, self.status = mapping, status or {}

    def get(self, url, params=None, timeout=None):
        doi = url.split("works/doi:", 1)[1]
        st = self.status.get(doi, 200)
        if st != 200:
            return _Resp({}, st)
        return _Resp({"doi": f"https://doi.org/{doi.upper()}", "cited_by_count": self.mapping[doi]})


def test_is_due_on_addition():
    assert is_due([], "2024-01-01", TODAY) is True  # never seen -> snapshot


def test_is_due_caps_at_three():
    snaps = [["2026-04-01", 1], ["2026-05-01", 2], ["2026-06-01", 3]]
    assert is_due(snaps, "2026-04-01", TODAY) is False


def test_is_due_only_within_three_months_of_publication():
    # published 5 months ago -> beyond tracking window, no further updates
    assert is_due([["2026-01-10", 1]], "2026-01-01", TODAY) is False
    # published 2 months ago, last snapshot in a prior month -> due
    assert is_due([["2026-05-10", 1]], "2026-04-01", TODAY) is True


def test_is_due_at_most_once_per_month():
    # already snapshotted this month -> not due again
    assert is_due([["2026-06-02", 1]], "2026-05-01", TODAY) is False


def test_record_snapshot_caps_and_orders():
    s = []
    for d, n in [("2026-04-01", 1), ("2026-05-01", 4), ("2026-06-01", 9), ("2026-07-01", 12)]:
        s = record_snapshot(s, d, n)
    assert len(s) == 3                      # keeps the most recent three
    assert s[-1] == ["2026-07-01", 12]
    assert latest_count(s) == 12


def test_citation_delta_is_rising_signal():
    assert citation_delta([["2026-04-01", 2], ["2026-06-01", 9]]) == 7
    assert citation_delta([["2026-04-01", 5]]) == 0   # single snapshot -> no velocity
    assert citation_delta([]) == 0


# ---- multi-source fetchers --------------------------------------------------
def test_fetch_counts_s2_parses_and_skips_unknown():
    sess = _S2Session({"10.1/a": 5, "10.1/b": 9})
    out = citations.fetch_counts_s2(["10.1/a", "10.1/b", "10.1/missing"], "key",
                                    session=sess, sleep=NO_SLEEP)
    assert out == {"10.1/a": 5, "10.1/b": 9}  # DOI echoed upper-cased -> normalised lower


def test_fetch_counts_openalex_single_work():
    sess = _OASession({"10.1/a": 7, "10.1/b": 3})
    out = citations.fetch_counts_openalex(["10.1/a", "10.1/b"], session=sess, sleep=NO_SLEEP)
    assert out == {"10.1/a": 7, "10.1/b": 3}


def test_fetch_counts_openalex_skips_404():
    sess = _OASession({"10.1/a": 7}, status={"10.1/b": 404})
    out = citations.fetch_counts_openalex(["10.1/a", "10.1/b"], session=sess, sleep=NO_SLEEP)
    assert out == {"10.1/a": 7}


def test_fetch_counts_openalex_returns_partial_on_429():
    # second DOI is budget-limited -> keep the first, do not raise
    sess = _OASession({"10.1/a": 7, "10.1/b": 1}, status={"10.1/b": 429})
    out = citations.fetch_counts_openalex(["10.1/a", "10.1/b"], session=sess,
                                          retries=0, sleep=NO_SLEEP)
    assert out == {"10.1/a": 7}


def test_merge_counts_keeps_maximum():
    assert citations.merge_counts({"a": 5, "b": 2}, {"a": 9, "c": 1}) == {"a": 9, "b": 2, "c": 1}


def test_fetch_counts_multi_merges_and_survives_provider_failure(monkeypatch):
    monkeypatch.setattr(citations, "fetch_counts_s2", lambda *a, **k: {"a": 5, "b": 4})

    def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(citations, "fetch_counts_openalex", boom)
    merged, sizes = citations.fetch_counts_multi(
        due_dois=["a", "b"], issn="", year="2024", use_crossref=False,
        s2_key="x", openalex_key="y",
    )
    assert merged == {"a": 5, "b": 4}        # S2 succeeds
    assert sizes == {"s2": 2, "openalex": 0}  # OpenAlex failure -> empty, not fatal
