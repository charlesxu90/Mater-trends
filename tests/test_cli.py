"""End-to-end CLI tests for the deterministic core (no network)."""

import json
import types

import pandas as pd

from mat_trend import rss
from mat_trend.cli import main


def _write_config(config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "taxonomy.json").write_text(
        json.dumps({"genome editing": ["crispr"], "immunology": ["t cell"]}), encoding="utf-8"
    )
    (config_dir / "useless_keywords.json").write_text(json.dumps(["method"]), encoding="utf-8")
    (config_dir / "journals.json").write_text(
        json.dumps({"journals": [{"key": "cell", "label": "Cell", "family": "Cell Press",
                                   "feeds": [{"url": "https://x/cell.rss"}]}]}),
        encoding="utf-8",
    )


def _write_papers(data_dir, key, month, rows):
    d = data_dir / key
    d.mkdir(parents=True, exist_ok=True)
    csv = d / f"{month}.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    return csv


def test_assign_writes_default_topics_path(tmp_path):
    config_dir = tmp_path / "config"
    _write_config(config_dir)
    csv = _write_papers(tmp_path / "data", "cell", "2026-05", [
        {"title": "CRISPR screen", "abstract": "cas9 work", "journal": "Cell"},
        {"title": "plant roots", "abstract": "", "journal": "Cell"},
    ])

    rc = main(["--config", str(config_dir), "assign", str(csv)])

    assert rc == 0
    out = csv.with_name(csv.name + "_topics.csv")
    assert out.exists()
    result = pd.read_csv(out)
    assert list(result["topic"].fillna("")) == ["genome editing", ""]


def test_trends_end_to_end(tmp_path, capsys):
    config_dir = tmp_path / "config"
    _write_config(config_dir)
    data_dir = tmp_path / "data"
    # two months so the later one has a baseline for emerging/fading
    for month, n_crispr in (("2026-04", 1), ("2026-05", 5)):
        rows = [{"title": "CRISPR screen", "abstract": "crispr", "journal": "Cell"} for _ in range(n_crispr)]
        rows.append({"title": "t cell study", "abstract": "t cell", "journal": "Cell"})
        csv = _write_papers(data_dir, "cell", month, rows)
        main(["--config", str(config_dir), "assign", str(csv)])

    rc = main(["--config", str(config_dir), "trends", "--data-dir", str(data_dir),
               "--min-count", "3", "--format", "json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    may = next(t for t in payload if t["period"] == "2026-05")
    assert may["group"] == "Cell"
    assert "genome editing" in may["top"]
    assert "genome editing" in may["emerging"]  # 1 -> 5 is a strong riser


def test_check_feeds_list_mode_no_network(tmp_path, capsys):
    config_dir = tmp_path / "config"
    _write_config(config_dir)
    rc = main(["--config", str(config_dir), "check-feeds"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "cell" in err and "https://x/cell.rss" in err


def test_ingest_cli_with_mocked_feed(tmp_path, monkeypatch, capsys):
    config_dir = tmp_path / "config"
    _write_config(config_dir)
    data_dir = tmp_path / "data"
    entries = [{"title": "CRISPR work", "prism_doi": "10.1016/j.cell.2026.05.009",
                "published": "2026-05-02", "link": "http://x/a", "summary": "crispr"}]
    fake = types.SimpleNamespace(status=200, entries=entries, feed={})
    monkeypatch.setattr(rss, "parse_feed", lambda url, agent=rss.USER_AGENT: fake)

    rc = main(["--config", str(config_dir), "ingest", "--data-dir", str(data_dir)])
    assert rc == 0
    saved = pd.read_csv(data_dir / "cell" / "2026-05.csv")
    assert saved.iloc[0]["title"] == "CRISPR work"


def test_ingest_cli_rejects_unknown_journal(tmp_path):
    config_dir = tmp_path / "config"
    _write_config(config_dir)
    rc = main(["--config", str(config_dir), "ingest", "--journal", "nope"])
    assert rc == 2
