"""Topic assignment is a deterministic substring match over lowercased text."""

import pandas as pd

from mat_trend.assign import assign_dataframe, build_search_text, topics_for_paper
from mat_trend.taxonomy import Taxonomy

TAX = Taxonomy(
    topic2keywords={
        "genome editing": ["crispr", "cas9"],
        "immunology": ["t cell", "antibody"],
    },
    useless_kw=set(),
)


def test_build_search_text_lowercases_and_joins():
    assert build_search_text("CRISPR Screen", "A T Cell study") == "crispr screen a t cell study"


def test_build_search_text_missing_abstract_is_empty():
    assert build_search_text("CRISPR", None) == "crispr "


def test_topics_match_in_taxonomy_order():
    text_title = "CRISPR base editing in T cell therapy"
    assert topics_for_paper(text_title, "antibody response", TAX) == "genome editing;immunology"


def test_no_match_returns_empty_string():
    assert topics_for_paper("A study of plant roots", "", TAX) == ""


def test_uppercase_keyword_never_matches():
    # keywords must be lowercase to match lowercased text
    tax = Taxonomy(topic2keywords={"x": ["CRISPR"]}, useless_kw=set())
    assert topics_for_paper("crispr screen", "", tax) == ""


def test_assign_dataframe_appends_topic_column():
    df = pd.DataFrame({"title": ["CRISPR work", "root growth"], "abstract": ["cas9", ""]})
    out = assign_dataframe(df, TAX)
    assert list(out["topic"]) == ["genome editing", ""]
