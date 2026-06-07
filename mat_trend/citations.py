"""Citation counts from Crossref (+ optional Semantic Scholar & OpenAlex), tracked
over time per paper.

Follows the Zotero *Citation Counts Manager* reference: Crossref's
``is-referenced-by-count`` keyed by DOI is the primary, key-less source. Every
Mater-trend article carries a DOI and Crossref is reachable where OpenAlex/S2 are
rate-limited, so Crossref is the default.

**Multi-source (optional).** When a Semantic Scholar and/or OpenAlex API key is
supplied, those providers are queried **in parallel** with Crossref for each
*(journal, year)* and the per-DOI counts are **merged by maximum** — the most
complete signal across providers, while keeping one integer per snapshot so the
velocity series stays comparable across runs. Keys come from the environment
(``S2_API_KEY`` / ``OPENALEX_API_KEY``); they are never stored in the repo.

Tracking policy (to surface *rising* papers): a paper's count is snapshotted
**on first sight (addition)** and then **at most twice more, monthly, while within
three months of its publication date** — three snapshots maximum. Citations of
older papers move slowly, so one snapshot is enough; recent papers accrue a short
velocity series, and the gain across snapshots is the "rising" signal.

Storage: ``citations/<journal_key>/<year>.json`` — committed (not under the
gitignored ``data/``) so history persists across checkouts/CI:

    { "<doi>": [["YYYY-MM-DD", count], ...] }   # oldest → newest, ≤ 3 entries

Efficiency: counts come from one paginated Crossref query per *(journal, year)*
(ISSN + date filter, selecting only DOI + count) — not one call per paper.
"""

from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    import requests

CROSSREF_WORKS = "https://api.crossref.org/works"
CROSSREF_WORK = "https://api.crossref.org/works/{doi}"
S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
OPENALEX_WORK = "https://api.openalex.org/works/doi:{doi}"
ROWS = 200
S2_BATCH = 500             # Semantic Scholar batch endpoint accepts ≤500 ids/call
S2_THROTTLE = 1.1          # S2 keys allow ~1 request/second, cumulative
OPENALEX_THROTTLE = 0.15   # free single-work endpoint; be polite
DEFAULT_THROTTLE = 0.5
DEFAULT_RETRIES = 5
DEFAULT_BACKOFF = 2.0
MAX_SNAPSHOTS = 3          # at most three updates per paper
TRACK_MONTHS = 3          # only keep updating within 3 months of publication

FETCH_FAILED = object()   # request itself failed (429/network) — do not cache

CITATIONS_DIR = Path(__file__).resolve().parent.parent / "citations"


# ---- history helpers --------------------------------------------------------
def counts_path(journal_key: str, year: str, base: Path | str = CITATIONS_DIR) -> Path:
    return Path(base) / journal_key / f"{year}.json"


def load_history(path: Path | str) -> dict[str, list]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def save_history(path: Path | str, history: dict[str, list]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def latest_count(snapshots: list) -> int | None:
    return snapshots[-1][1] if snapshots else None


def citation_delta(snapshots: list) -> int:
    """Gain between the first and latest snapshot (the rising signal); 0 if <2."""
    if not snapshots or len(snapshots) < 2:
        return 0
    return snapshots[-1][1] - snapshots[0][1]


def _months_between(pub_date: str, today: datetime.date) -> int | None:
    if not isinstance(pub_date, str) or len(pub_date) < 7 or pub_date[4] != "-":
        return None
    y, m = int(pub_date[:4]), int(pub_date[5:7])
    return (today.year - y) * 12 + (today.month - m)


def is_due(snapshots: list, pub_date: str, today: datetime.date) -> bool:
    """Whether a paper should be (re)snapshotted now.

    * No snapshot yet -> due (addition).
    * Otherwise only while < MAX_SNAPSHOTS, within TRACK_MONTHS of publication, and
      not already snapshotted this calendar month.
    """
    if not snapshots:
        return True
    if len(snapshots) >= MAX_SNAPSHOTS:
        return False
    months = _months_between(pub_date, today)
    if months is None or months > TRACK_MONTHS:
        return False
    return snapshots[-1][0][:7] < today.strftime("%Y-%m")


def record_snapshot(snapshots: list, date_iso: str, count: int) -> list:
    """Append a snapshot (immutably), keeping the last MAX_SNAPSHOTS."""
    return [*snapshots, [date_iso, count]][-MAX_SNAPSHOTS:]


# ---- Crossref fetch ---------------------------------------------------------
def _session(mailto: str = "", session: "requests.Session | None" = None) -> "requests.Session":
    import requests

    sess = session or requests.Session()
    sess.headers.setdefault("User-Agent", f"mat-trend/0.1 (mailto:{mailto})" if mailto else "mat-trend/0.1")
    return sess


def count_by_doi(
    doi: str, session: "requests.Session", *,
    retries: int = DEFAULT_RETRIES, backoff: float = DEFAULT_BACKOFF, sleep=time.sleep,
) -> int | None | object:
    """Crossref ``is-referenced-by-count`` for a single DOI (reference behaviour)."""
    for attempt in range(retries + 1):
        try:
            resp = session.get(CROSSREF_WORK.format(doi=doi), timeout=30)
            if resp.status_code == 404:
                return None
            if resp.status_code == 429:
                if attempt < retries:
                    sleep(backoff * (2 ** attempt)); continue
                return FETCH_FAILED
            resp.raise_for_status()
            return resp.json().get("message", {}).get("is-referenced-by-count")
        except Exception:
            if attempt < retries:
                sleep(backoff * (2 ** attempt)); continue
            return FETCH_FAILED
    return FETCH_FAILED


def fetch_counts_for_source(
    issn: str, *, from_date: str, to_date: str, mailto: str = "",
    session: "requests.Session | None" = None, throttle: float = DEFAULT_THROTTLE,
    retries: int = DEFAULT_RETRIES, backoff: float = DEFAULT_BACKOFF, sleep=time.sleep,
    log: Callable[[str], None] = lambda *_: None,
) -> dict[str, int]:
    """``{doi: is-referenced-by-count}`` for a journal (ISSN) in a date range."""
    sess = _session(mailto, session)
    filt = f"issn:{issn},from-pub-date:{from_date},until-pub-date:{to_date},type:journal-article"
    counts: dict[str, int] = {}
    cursor = "*"
    while cursor:
        params = {"filter": filt, "rows": ROWS, "cursor": cursor,
                  "select": "DOI,is-referenced-by-count"}
        if mailto:
            params["mailto"] = mailto
        data = None
        for attempt in range(retries + 1):
            try:
                resp = sess.get(CROSSREF_WORKS, params=params, timeout=60)
                if resp.status_code == 429:
                    if attempt < retries:
                        sleep(backoff * (2 ** attempt)); continue
                    raise RuntimeError("Crossref rate-limited (429) after retries")
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception:
                if attempt < retries:
                    sleep(backoff * (2 ** attempt)); continue
                raise
        message = data.get("message", {})
        items = message.get("items", [])
        for it in items:
            doi = (it.get("DOI") or "").strip().lower()
            n = it.get("is-referenced-by-count")
            if doi and isinstance(n, int):
                counts[doi] = n
        cursor = message.get("next-cursor")
        log(f"  {issn}: {len(counts)} counts so far…")
        if not items:
            break
        sleep(throttle)
    return counts


# ---- Semantic Scholar & OpenAlex (optional, keyed) --------------------------
def _chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def fetch_counts_s2(
    dois, api_key: str, *, session: "requests.Session | None" = None,
    batch: int = S2_BATCH, throttle: float = S2_THROTTLE,
    retries: int = DEFAULT_RETRIES, backoff: float = DEFAULT_BACKOFF, sleep=time.sleep,
    log: Callable[[str], None] = lambda *_: None,
) -> dict[str, int]:
    """``{doi: citationCount}`` from Semantic Scholar's batch endpoint.

    One POST per ``batch`` DOIs (≤500); the S2 key allows ~1 request/second, so we
    sleep ``throttle`` between calls. DOIs unknown to S2 come back ``null`` and are
    skipped. Results are keyed by the DOI S2 echoes back (lowercased).
    """
    sess = session or _session()
    headers = {"x-api-key": api_key} if api_key else {}
    chunks = list(_chunked([d for d in dois if d], batch))
    counts: dict[str, int] = {}
    for idx, chunk in enumerate(chunks):
        data = None
        for attempt in range(retries + 1):
            try:
                resp = sess.post(
                    S2_BATCH_URL, params={"fields": "citationCount,externalIds"},
                    json={"ids": [f"DOI:{d}" for d in chunk]}, headers=headers, timeout=60,
                )
                if resp.status_code == 429:
                    if attempt < retries:
                        sleep(backoff * (2 ** attempt)); continue
                    raise RuntimeError("Semantic Scholar rate-limited (429) after retries")
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception:
                if attempt < retries:
                    sleep(backoff * (2 ** attempt)); continue
                raise
        for item in data or []:
            if not item:
                continue  # S2 returns null for ids it does not know
            n = item.get("citationCount")
            doi = ((item.get("externalIds") or {}).get("DOI") or "").strip().lower()
            if doi and isinstance(n, int):
                counts[doi] = n
        log(f"  s2: {len(counts)} counts so far…")
        if idx < len(chunks) - 1:
            sleep(throttle)
    return counts


def fetch_counts_openalex(
    dois, *, api_key: str = "", mailto: str = "", session: "requests.Session | None" = None,
    throttle: float = OPENALEX_THROTTLE, retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF, sleep=time.sleep,
    log: Callable[[str], None] = lambda *_: None,
) -> dict[str, int]:
    """``{doi: cited_by_count}`` from OpenAlex's free single-work endpoint, one DOI
    per request.

    OpenAlex's bulk list/filter endpoint is metered and needs a funded key, whereas
    the single-work lookup is free — so we use the latter and run OpenAlex on its own
    thread alongside the other providers. If OpenAlex starts refusing with 429
    (budget exhausted), we stop early and return whatever was collected rather than
    failing the run.
    """
    sess = session or _session(mailto)
    clean = [d for d in dois if d]
    counts: dict[str, int] = {}
    for i, doi in enumerate(clean):
        params = {"select": "doi,cited_by_count"}
        if api_key:
            params["api_key"] = api_key
        if mailto:
            params["mailto"] = mailto
        data: dict | None = None
        for attempt in range(retries + 1):
            try:
                resp = sess.get(OPENALEX_WORK.format(doi=doi), params=params, timeout=30)
                if resp.status_code == 404:
                    data = {}; break
                if resp.status_code == 429:
                    if attempt < retries:
                        sleep(backoff * (2 ** attempt)); continue
                    log(f"  openalex: 429 (budget?) — returning {len(counts)} partial")
                    return counts
                resp.raise_for_status()
                data = resp.json(); break
            except Exception:
                if attempt < retries:
                    sleep(backoff * (2 ** attempt)); continue
                raise
        n = (data or {}).get("cited_by_count")
        echoed = ((data or {}).get("doi") or "").strip().lower().replace("https://doi.org/", "")
        if isinstance(n, int):
            counts[echoed or doi] = n
        if (i + 1) % 100 == 0:
            log(f"  openalex: {len(counts)} counts so far…")
        if i < len(clean) - 1:
            sleep(throttle)
    return counts


# ---- merge + parallel orchestration -----------------------------------------
def merge_counts(*sources: dict[str, int]) -> dict[str, int]:
    """Combine per-source ``{doi: count}`` maps, keeping the **maximum** count per
    DOI — the most complete signal across providers."""
    merged: dict[str, int] = {}
    for src in sources:
        for doi, n in (src or {}).items():
            if isinstance(n, int) and (doi not in merged or n > merged[doi]):
                merged[doi] = n
    return merged


def fetch_counts_multi(
    *, due_dois, issn: str, year: str, use_crossref: bool = True,
    s2_key: str | None = None, openalex_key: str | None = None, mailto: str = "",
    throttle: float = DEFAULT_THROTTLE, sleep=time.sleep,
    log: Callable[[str], None] = lambda *_: None,
) -> tuple[dict[str, int], dict[str, int]]:
    """Query every enabled provider for one *(journal, year)* **concurrently** and
    return ``(merged_counts, per_source_sizes)``.

    Each provider runs on its own thread with its own HTTP session (``requests``
    sessions are not safe to share across threads). A provider that errors yields
    an empty map rather than failing the whole fetch; counts are merged by max.
    """
    from concurrent.futures import ThreadPoolExecutor

    jobs: dict[str, Callable[[], dict[str, int]]] = {}
    if use_crossref and issn:
        jobs["crossref"] = lambda: fetch_counts_for_source(
            issn, from_date=f"{year}-01-01", to_date=f"{year}-12-31",
            mailto=mailto, throttle=throttle, sleep=sleep, log=log,
        )
    if s2_key:
        jobs["s2"] = lambda: fetch_counts_s2(list(due_dois), s2_key, sleep=sleep, log=log)
    if openalex_key:
        jobs["openalex"] = lambda: fetch_counts_openalex(
            list(due_dois), api_key=openalex_key, mailto=mailto, sleep=sleep, log=log)

    results: dict[str, dict[str, int]] = {}
    if jobs:
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {pool.submit(fn): name for name, fn in jobs.items()}
            for fut, name in futures.items():
                try:
                    results[name] = fut.result()
                except Exception as exc:  # one provider down must not sink the rest
                    log(f"  {name} failed ({type(exc).__name__}: {exc})")
                    results[name] = {}
    return merge_counts(*results.values()), {n: len(r) for n, r in results.items()}
