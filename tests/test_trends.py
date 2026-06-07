"""Trend computation: top/emerging/fading and time bucketing."""

from mat_trend.trends import bucket_for, compute_trends


def test_top_is_by_current_count():
    current = {"a": 10, "b": 5, "c": 1, "d": 0}
    trend = compute_trends("Cell", "2026-06", current, None, top_n=2)
    assert trend.top == ["a", "b"]
    assert trend.emerging == [] and trend.fading == []  # no previous period


def test_emerging_requires_baseline_and_current_volume():
    previous = {"a": 2, "b": 10, "c": 0}
    current = {"a": 8, "b": 11, "c": 9}  # c is 0->9 (infinite ratio) excluded by min_prev
    trend = compute_trends("Cell", "2026-06", current, previous, top_n=2, min_prev=1, min_count=3)
    # a: ratio (8-2)/2=3.0 ; b: (11-10)/10=0.1 ; c excluded (prev 0)
    assert trend.emerging[0] == "a"
    assert "c" not in trend.emerging


def test_emerging_excludes_low_current_volume():
    previous = {"a": 1}
    current = {"a": 2}  # ratio 1.0 but current 2 < min_count 3 -> not emerging
    trend = compute_trends("Cell", "2026-06", current, previous, min_count=3)
    assert "a" not in trend.emerging


def test_fading_is_lowest_ratio():
    previous = {"a": 10, "b": 10}
    current = {"a": 2, "b": 12}
    trend = compute_trends("Cell", "2026-06", current, previous, top_n=1, min_prev=1)
    assert trend.fading == ["a"]  # a shrank


def test_bucket_for_quarter():
    assert bucket_for("2026-05", "quarter") == "2026-Q2"
    assert bucket_for("2026-01", "quarter") == "2026-Q1"
    assert bucket_for("2026-12", "quarter") == "2026-Q4"


def test_bucket_for_month_is_identity():
    assert bucket_for("2026-05", "month") == "2026-05"


def test_bucket_for_year():
    assert bucket_for("2026-05", "year") == "2026"
    assert bucket_for("2025-12", "year") == "2025"
