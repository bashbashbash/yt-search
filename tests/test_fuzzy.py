import pytest
from ytsearch import fuzzy_score, rank_results


# ─── fuzzy_score ──────────────────────────────────────────────────────────────

def test_exact_match_scores_highest():
    """An entry whose title exactly matches the query scores higher than a partial match."""
    exact = {"title": "mozart piano concerto", "uploader": "someone"}
    partial = {"title": "beethoven symphony", "uploader": "someone"}
    assert fuzzy_score("mozart piano concerto", exact) > fuzzy_score("mozart piano concerto", partial)


def test_word_bonus_boosts_score():
    """An entry containing all query words scores higher than one with none."""
    all_words = {"title": "mozart piano concerto no 9", "uploader": ""}
    no_words = {"title": "vivaldi four seasons", "uploader": ""}
    score_all = fuzzy_score("mozart piano concerto", all_words)
    score_none = fuzzy_score("mozart piano concerto", no_words)
    assert score_all > score_none


def test_missing_title_scores_zero():
    """An entry with no title and no uploader returns 0.0 without crashing."""
    entry = {"uploader": ""}
    score = fuzzy_score("mozart", entry)
    assert score == 0.0


# ─── rank_results ─────────────────────────────────────────────────────────────

def test_rank_results_order():
    """Given mixed entries, rank_results returns them sorted best-first."""
    entries = [
        {"title": "vivaldi four seasons", "uploader": ""},
        {"title": "mozart piano concerto no 9", "uploader": ""},
        {"title": "beethoven symphony no 5", "uploader": ""},
    ]
    ranked = rank_results("mozart piano concerto", entries)
    assert ranked[0]["title"] == "mozart piano concerto no 9"


def test_rank_results_empty():
    """rank_results with an empty list returns empty list without crashing."""
    assert rank_results("mozart", []) == []


def test_rank_results_skips_entries_without_title():
    """Entries missing a title field are excluded from ranked results."""
    entries = [
        {"title": "mozart piano concerto", "uploader": ""},
        {"uploader": "no title here"},
    ]
    ranked = rank_results("mozart piano concerto", entries)
    assert len(ranked) == 1
    assert ranked[0]["title"] == "mozart piano concerto"
