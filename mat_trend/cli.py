"""``mat-trend`` command-line interface.

Subcommands:

* ``check-feeds`` — list tracked feeds; with ``--check``, probe each for liveness.
* ``ingest``      — poll RSS feeds and accumulate articles into the data store.
* ``candidates``  — extract candidate keywords (spaCy NER) for the curate-topics skill.
* ``curate``      — apply the skill's decision JSON to the taxonomy config.
* ``assign``      — assign topics to a papers CSV using the current taxonomy.
* ``trends``      — compute top/emerging/fading topics per journal/family period.
* ``citations``   — fetch citation counts (DOI-first, cached) for trending papers.
* ``export-site`` — build static-site JSON for GitHub Pages.
* ``refresh``     — full pipeline: ingest -> assign -> trends -> export-site.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mat_trend.taxonomy import DEFAULT_CONFIG_DIR, Taxonomy

OTHER_LEDGER_FILENAME = "other_keywords.json"


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


def _load_other_ledger(config_dir: Path) -> list[str]:
    path = config_dir / OTHER_LEDGER_FILENAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _save_other_ledger(config_dir: Path, keywords: list[str]) -> None:
    (config_dir / OTHER_LEDGER_FILENAME).write_text(
        json.dumps(sorted(set(keywords)), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _default_topics_path(csv_path: Path) -> Path:
    return csv_path.with_name(csv_path.name + "_topics.csv")


# ---- subcommands ------------------------------------------------------------
def cmd_check_feeds(args: argparse.Namespace) -> int:
    from mat_trend.registry import JournalRegistry

    registry = JournalRegistry.load(Path(args.config))
    pairs = registry.all_feeds()
    _eprint(f"feeds: {len(pairs)} across {len(registry.journals)} journal(s)")
    if not args.check:
        for journal, feed in pairs:
            _eprint(f"  {journal.key:20s} {journal.frequency:10s} {feed.type:8s} {feed.url}")
        return 0

    from mat_trend.rss import feed_status

    dead = 0
    for journal, feed in pairs:
        ok, status, n = feed_status(feed.url)
        mark = "OK " if ok else "DEAD"
        if not ok:
            dead += 1
        _eprint(f"  [{mark}] http={status or '-'} entries={n:<4d} {journal.key} -> {feed.url}")
    _eprint(f"check: {len(pairs) - dead}/{len(pairs)} feeds live, {dead} dead")
    return 1 if dead else 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from mat_trend.ingest import ingest_all
    from mat_trend.registry import JournalRegistry

    registry = JournalRegistry.load(Path(args.config))
    only = {k.strip() for k in args.journal.split(",")} if args.journal else None
    if only:
        unknown = only - set(registry.keys)
        if unknown:
            _eprint(f"error: unknown journal key(s): {sorted(unknown)}")
            return 2
    summary = ingest_all(registry, args.data_dir, only=only, force=args.force, log=_eprint)
    total = sum(sum(v.values()) for v in summary.values())
    _eprint(f"ingest: +{total} new article(s) across {len(summary)} journal(s) -> {args.data_dir}")
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    import os

    from mat_trend.backfill import backfill_all
    from mat_trend.registry import JournalRegistry

    registry = JournalRegistry.load(Path(args.config))
    only = {k.strip() for k in args.journal.split(",")} if args.journal else None
    if only:
        unknown = only - set(registry.keys)
        if unknown:
            _eprint(f"error: unknown journal key(s): {sorted(unknown)}")
            return 2
    try:
        years = [int(y.strip()) for y in args.years.split(",") if y.strip()]
    except ValueError:
        _eprint(f"error: --years must be comma-separated integers, got {args.years!r}")
        return 2

    mailto = args.mailto or os.environ.get("OPENALEX_MAILTO", "")
    totals = backfill_all(registry, years, args.data_dir, only=only, mailto=mailto, log=_eprint)
    grand = sum(totals.values())
    _eprint(f"backfill: +{grand} article(s) across {len(totals)} journal(s) for years {years} -> {args.data_dir}")
    return 0


def cmd_candidates(args: argparse.Namespace) -> int:
    import pandas as pd

    from mat_trend.candidates import candidate_keywords, candidates_to_dicts
    from mat_trend.curate_io import build_curation_payload

    csv_path = Path(args.csv)
    if not csv_path.exists():
        _eprint(f"error: input CSV not found: {csv_path}")
        return 2

    config_dir = Path(args.config)
    taxonomy = Taxonomy.load(config_dir)
    ledger = _load_other_ledger(config_dir)
    if ledger:
        taxonomy = taxonomy.add_noise(ledger)

    df = pd.read_csv(csv_path)
    if "title" not in df.columns:
        _eprint(f"error: CSV has no 'title' column: {csv_path}")
        return 2
    titles = df["title"].astype(str).str.lower().tolist()

    candidates = candidate_keywords(
        titles, taxonomy, model_path=args.model, threshold=args.threshold, examples=args.examples,
    )
    payload = build_curation_payload(candidates, taxonomy, journal=args.journal, period=args.period)
    payload["candidates"] = candidates_to_dicts(candidates)

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        _eprint(f"wrote {len(candidates)} candidates -> {args.output}")
    else:
        print(text)
    return 0


def cmd_curate(args: argparse.Namespace) -> int:
    from mat_trend.curate_io import apply_decision, parse_decision

    decision_path = Path(args.decision)
    if not decision_path.exists():
        _eprint(f"error: decision file not found: {decision_path}")
        return 2

    config_dir = Path(args.config)
    taxonomy = Taxonomy.load(config_dir)
    decisions = parse_decision(json.loads(decision_path.read_text(encoding="utf-8")))
    result = apply_decision(taxonomy, decisions)

    if args.dry_run:
        _eprint(f"dry-run: {result.summary}; other={result.other_keywords}")
        return 0

    result.taxonomy.save(config_dir)
    if result.other_keywords:
        ledger = _load_other_ledger(config_dir)
        _save_other_ledger(config_dir, [*ledger, *result.other_keywords])
    _eprint(f"applied {result.summary}; parked {len(result.other_keywords)} in 'other'")
    return 0


def cmd_assign(args: argparse.Namespace) -> int:
    from mat_trend.assign import assign_csv

    csv_path = Path(args.csv)
    if not csv_path.exists():
        _eprint(f"error: input CSV not found: {csv_path}")
        return 2

    taxonomy = Taxonomy.load(Path(args.config))
    out_path = Path(args.output) if args.output else _default_topics_path(csv_path)
    assign_csv(str(csv_path), str(out_path), taxonomy)
    _eprint(f"assigned topics -> {out_path}")
    return 0


def cmd_trends(args: argparse.Namespace) -> int:
    from mat_trend.registry import JournalRegistry
    from mat_trend.trends import compute_all_trends, render_markdown, trend_to_dict

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        _eprint(f"error: data directory not found: {data_dir}")
        return 2

    taxonomy = Taxonomy.load(Path(args.config))
    registry = JournalRegistry.load(Path(args.config))
    trends = compute_all_trends(
        taxonomy, data_dir, group_by=args.group_by, bucket=args.bucket,
        top_n=args.top_n, min_prev=args.min_prev, min_count=args.min_count,
        key_to_label=registry.key_to_label, key_to_family=registry.key_to_family,
    )
    if not trends:
        _eprint(f"error: no *_topics.csv found under {data_dir} (run ingest + assign first)")
        return 2

    if args.format == "markdown":
        text = render_markdown(trends)
    else:
        text = json.dumps(
            [trend_to_dict(t, include_counts=args.include_counts) for t in trends],
            indent=2, ensure_ascii=False,
        )

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        _eprint(f"wrote trends for {len(trends)} group-period(s) -> {args.output}")
    else:
        print(text)
    return 0


def cmd_citations(args: argparse.Namespace) -> int:
    import datetime
    import os
    from collections import defaultdict

    import pandas as pd

    from mat_trend import citations as C
    from mat_trend.registry import JournalRegistry

    registry = JournalRegistry.load(Path(args.config))
    only = {k.strip() for k in args.journal.split(",")} if args.journal else None
    year_filter = {y.strip() for y in args.years.split(",")} if args.years else None
    today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    mailto = args.mailto or os.environ.get("OPENALEX_MAILTO", "")

    # API keys come from the environment (or --flags); never stored in the repo.
    s2_key = (args.s2_key or os.environ.get("S2_API_KEY") or "").strip() or None
    openalex_key = (args.openalex_key or os.environ.get("OPENALEX_API_KEY") or "").strip() or None
    use_crossref = not args.no_crossref
    if args.no_s2:
        s2_key = None
    if args.no_openalex:
        openalex_key = None

    enabled = [name for name, on in (
        ("Crossref", use_crossref), ("Semantic Scholar", bool(s2_key)), ("OpenAlex", bool(openalex_key)),
    ) if on]
    if not enabled:
        _eprint("citations: no sources enabled — pass an S2/OpenAlex key or drop --no-crossref")
        return 1
    _eprint(f"citations: sources = {', '.join(enabled)} (queried in parallel, merged by max)")

    data_dir = Path(args.data_dir)

    # Optional scope: restrict recorded papers to those whose assigned topic is in
    # the top/emerging set for their journal-year (the Crossref bulk fetch is
    # unchanged — this only narrows which DOIs get a snapshot recorded).
    trending_only = getattr(args, "trending_only", False)
    trending_by_key: dict[str, dict[str, set]] = {}
    if trending_only:
        from mat_trend.trends import compute_all_trends

        taxonomy = Taxonomy.load(Path(args.config))
        label_to_key = {v: k for k, v in registry.key_to_label.items()}
        for t in compute_all_trends(
            taxonomy, data_dir, group_by="journal", bucket="year",
            key_to_label=registry.key_to_label, key_to_family=registry.key_to_family,
        ):
            key = label_to_key.get(t.group)
            if key is None:
                continue
            trending_by_key.setdefault(key, {}).setdefault(t.period, set()).update(t.top, t.emerging)
        n_topics = sum(len(v) for d in trending_by_key.values() for v in d.values())
        _eprint(f"citations: --trending-only — {n_topics} (journal,year,topic) trend slots")

    total_new = 0

    for journal in registry.journals:
        if only and journal.key not in only:
            continue
        key_dir = data_dir / journal.key
        if not key_dir.exists():
            continue

        # gather {year: {doi: published_date}} from the monthly source CSVs, and
        # (when --trending-only) {year: {doi: {topics}}} from the *_topics.csv files
        years: dict[str, dict[str, str]] = defaultdict(dict)
        doi_topics: dict[str, dict[str, set]] = defaultdict(dict)
        for csv in sorted(key_dir.glob("*.csv")):
            if csv.name.endswith("_topics.csv") or len(csv.stem) != 7:
                continue
            year = csv.stem[:4]
            df = pd.read_csv(csv, usecols=lambda c: c in ("doi", "published_date"))
            for doi, pub in zip(df.get("doi", []), df.get("published_date", [])):
                doi = str(doi).strip().lower()
                if doi and doi != "nan":
                    years[year][doi] = str(pub or "")
            if trending_only:
                tpath = csv.with_name(csv.name + "_topics.csv")
                if tpath.exists():
                    tdf = pd.read_csv(tpath, usecols=lambda c: c in ("doi", "topic"))
                    for doi, topic in zip(tdf.get("doi", []), tdf.get("topic", [])):
                        doi = str(doi).strip().lower()
                        topic = str(topic)
                        if doi and doi != "nan":
                            doi_topics[year][doi] = set(topic.split(";")) if topic and topic != "nan" else set()

        for year, doi_pub in sorted(years.items()):
            if year_filter and year not in year_filter:
                continue
            path = C.counts_path(journal.key, year)
            history = C.load_history(path)
            due = [d for d, pub in doi_pub.items() if C.is_due(history.get(d, []), pub, today)]
            if trending_only:
                allow = trending_by_key.get(journal.key, {}).get(year, set())
                topics_for_year = doi_topics.get(year, {})
                due = [d for d in due if topics_for_year.get(d, set()) & allow]
            if not due:
                continue
            _eprint(f"citations: {journal.key} {year} — {len(due)} due; querying {len(enabled)} source(s)…")
            try:
                counts, sizes = C.fetch_counts_multi(
                    due_dois=due, issn=journal.issn or "", year=year,
                    use_crossref=use_crossref, s2_key=s2_key, openalex_key=openalex_key,
                    mailto=mailto, throttle=args.throttle,
                )
            except Exception as exc:
                _eprint(f"citations: {journal.key} {year} failed ({type(exc).__name__}: {exc})")
                continue
            n_new = 0
            for doi in due:
                if doi in counts:
                    history[doi] = C.record_snapshot(history.get(doi, []), today.isoformat(), counts[doi])
                    n_new += 1
            C.save_history(path, history)
            total_new += n_new
            srcs = ", ".join(f"{k} {v}" for k, v in sizes.items())
            _eprint(f"citations: {journal.key} {year} +{n_new} snapshot(s) [{srcs}] -> {path}")

    _eprint(f"citations: {total_new} snapshot(s) recorded; re-run export-site to surface them")
    return 0


def cmd_export_site(args: argparse.Namespace) -> int:
    from mat_trend.site import export_site

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        _eprint(f"error: data directory not found: {data_dir}")
        return 2

    taxonomy = Taxonomy.load(Path(args.config))
    manifest = export_site(
        args.out_dir, taxonomy=taxonomy, data_dir=data_dir,
        group_by=args.group_by, bucket=args.bucket,
        top_n=args.top_n, min_prev=args.min_prev, min_count=args.min_count,
        abstract_chars=args.abstract_chars, shard_years=args.shard_years or None,
    )
    papers = sum(s["count"] for s in manifest["shards"])
    _eprint(f"exported {len(manifest['shards'])} shards / {papers} papers -> {args.out_dir}")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    from mat_trend.refresh import refresh

    only = {k.strip() for k in args.journal.split(",")} if args.journal else None
    summary = refresh(
        config_dir=Path(args.config), data_dir=args.data_dir, site_dir=args.site_dir,
        do_ingest=not args.no_ingest, only=only, force=args.force,
        group_by=args.group_by, bucket=args.bucket,
        shard_years=args.shard_years or None, log=_eprint,
    )
    _eprint(f"refresh complete: {summary}")
    return 0


# ---- parser -----------------------------------------------------------------
def _add_trend_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--group-by", choices=["journal", "family"], default="journal")
    p.add_argument("--bucket", choices=["month", "quarter", "year"], default="month")
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--min-prev", type=int, default=1)
    p.add_argument("--min-count", type=int, default=3)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mat-trend", description=__doc__)
    parser.add_argument(
        "--config", default=str(DEFAULT_CONFIG_DIR),
        help="config dir holding journals.json / taxonomy.json / useless_keywords.json",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_chk = sub.add_parser("check-feeds", help="list tracked feeds; --check probes liveness")
    p_chk.add_argument("--check", action="store_true", help="probe each feed over the network")
    p_chk.set_defaults(func=cmd_check_feeds)

    p_ing = sub.add_parser("ingest", help="poll due RSS feeds and accumulate articles")
    p_ing.add_argument("--journal", default=None, help="comma-separated journal keys (default: all)")
    p_ing.add_argument("--force", action="store_true", help="poll even journals not yet due per their frequency")
    p_ing.add_argument("--data-dir", default="data")
    p_ing.set_defaults(func=cmd_ingest)

    p_bf = sub.add_parser("backfill", help="fetch historical articles from Crossref into the store")
    p_bf.add_argument("--years", default=None, required=True, help="comma-separated years, e.g. 2024,2025")
    p_bf.add_argument("--journal", default=None, help="comma-separated journal keys (default: all)")
    p_bf.add_argument("--mailto", default=None, help="contact email for Crossref polite pool (or $OPENALEX_MAILTO)")
    p_bf.add_argument("--data-dir", default="data")
    p_bf.set_defaults(func=cmd_backfill)

    p_cand = sub.add_parser("candidates", help="extract candidate keywords for curation")
    p_cand.add_argument("csv", help="papers CSV (needs a 'title' column)")
    p_cand.add_argument("-o", "--output", help="write payload JSON here (default: stdout)")
    p_cand.add_argument("--threshold", type=int, default=5, help="min keyword count")
    p_cand.add_argument("--examples", type=int, default=3, help="example titles / keyword")
    p_cand.add_argument("--model", default=None, help="spaCy model path or package name (default: en_core_web_lg)")
    p_cand.add_argument("--journal", default=None)
    p_cand.add_argument("--period", default=None)
    p_cand.set_defaults(func=cmd_candidates)

    p_cur = sub.add_parser("curate", help="apply a curation decision to the taxonomy")
    p_cur.add_argument("decision", help="decision JSON produced by the curate-topics skill")
    p_cur.add_argument("--dry-run", action="store_true", help="report changes, write nothing")
    p_cur.set_defaults(func=cmd_curate)

    p_asg = sub.add_parser("assign", help="assign topics to a papers CSV")
    p_asg.add_argument("csv", help="papers CSV (needs 'title' and 'abstract' columns)")
    p_asg.add_argument("-o", "--output", help="output CSV (default: <csv>_topics.csv)")
    p_asg.set_defaults(func=cmd_assign)

    p_trd = sub.add_parser("trends", help="compute top/emerging/fading topics")
    p_trd.add_argument("--data-dir", default="data", help="root holding <journal_key>/ folders")
    p_trd.add_argument("-o", "--output", help="output file (default: stdout)")
    p_trd.add_argument("--format", choices=["json", "markdown"], default="json")
    p_trd.add_argument("--include-counts", action="store_true", help="embed per-topic counts (json)")
    _add_trend_opts(p_trd)
    p_trd.set_defaults(func=cmd_trends)

    p_cit = sub.add_parser("citations", help="track citation counts per paper from Crossref + optional Semantic Scholar & OpenAlex (parallel, merged by max; on addition + monthly for 3 months)")
    p_cit.add_argument("--journal", default=None, help="comma-separated journal keys (default: all)")
    p_cit.add_argument("--years", default=None, help="comma-separated years (default: all present)")
    p_cit.add_argument("--mailto", default=None, help="contact email for Crossref/OpenAlex polite pool (or $OPENALEX_MAILTO)")
    p_cit.add_argument("--s2-key", default=None, help="Semantic Scholar API key (or $S2_API_KEY); enables the S2 source")
    p_cit.add_argument("--openalex-key", default=None, help="OpenAlex API key (or $OPENALEX_API_KEY); enables the OpenAlex source")
    p_cit.add_argument("--no-crossref", action="store_true", help="skip the Crossref source")
    p_cit.add_argument("--no-s2", action="store_true", help="skip Semantic Scholar even if a key is set")
    p_cit.add_argument("--no-openalex", action="store_true", help="skip OpenAlex even if a key is set")
    p_cit.add_argument("--data-dir", default="data")
    p_cit.add_argument("--throttle", type=float, default=0.5, help="seconds between Crossref pages")
    p_cit.add_argument("--today", default=None, help="override today's date (YYYY-MM-DD), for scheduling/testing")
    p_cit.add_argument("--trending-only", action="store_true",
                       help="only record papers whose topic is top/emerging for their journal-year")
    p_cit.set_defaults(func=cmd_citations)

    p_exp = sub.add_parser("export-site", help="build static-site JSON for GitHub Pages")
    p_exp.add_argument("--data-dir", default="data")
    p_exp.add_argument("--out-dir", default="docs/data")
    p_exp.add_argument("--abstract-chars", type=int, default=300)
    p_exp.add_argument("--shard-years", type=int, default=0,
                       help="cap browsable paper shards to the most recent N years (0 = all); trends always use full history")
    _add_trend_opts(p_exp)
    p_exp.set_defaults(func=cmd_export_site)

    p_ref = sub.add_parser("refresh", help="full pipeline (ingest->assign->trends->export-site)")
    p_ref.add_argument("--no-ingest", action="store_true", help="skip polling; re-derive from existing data")
    p_ref.add_argument("--force", action="store_true", help="poll even journals not yet due per their frequency")
    p_ref.add_argument("--journal", default=None, help="comma-separated keys to ingest (default: all)")
    p_ref.add_argument("--data-dir", default="data")
    p_ref.add_argument("--site-dir", default="docs/data")
    p_ref.add_argument("--group-by", choices=["journal", "family"], default="journal")
    p_ref.add_argument("--bucket", choices=["month", "quarter", "year"], default="month")
    p_ref.add_argument("--shard-years", type=int, default=0,
                       help="cap browsable paper shards to the most recent N years (0 = all)")
    p_ref.set_defaults(func=cmd_refresh)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "model", None) is None and args.command == "candidates":
        from mat_trend.candidates import DEFAULT_MODEL_PATH

        args.model = str(DEFAULT_MODEL_PATH)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
