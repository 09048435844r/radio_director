"""hallucination_detector の単体テスト。"""

from __future__ import annotations

from radio_director.phase_d.hallucination_detector import (
    build_fact_index,
    check_needs_review_usage,
    detect_hallucinations,
)
from radio_director.phase_d.number_extractor import ExtractedNumber, extract_numbers

from tests.phase_a._factories import kn
from tests.phase_d._factories import (
    make_cleaned_research,
    make_script,
    make_segment,
)


def _ext(canonical, raw=None, segment_id="deep_dive_0", highly=False):
    return ExtractedNumber(
        canonical=canonical,
        raw=raw or canonical,
        segment_id=segment_id,
        is_highly_specific=highly,
    )


def test_all_match_no_warnings():
    cleaned = make_cleaned_research()
    idx = build_fact_index(cleaned)
    assert "39.5%" in idx
    assert "2.94倍" in idx

    extracted = [_ext("39.5%"), _ext("2.94倍")]
    stats, warnings = detect_hallucinations(extracted, idx)
    assert stats.matched == 2
    assert stats.unmatched == 0
    assert stats.matched_ratio == 1.0
    assert warnings == []


def test_unmatched_emits_warning():
    cleaned = make_cleaned_research()
    idx = build_fact_index(cleaned)
    extracted = [_ext("39.5%"), _ext("999.9%")]
    stats, warnings = detect_hallucinations(extracted, idx)
    assert stats.matched == 1
    assert stats.unmatched == 1
    codes = [w.code for w in warnings]
    assert "unmatched_number" in codes


def test_highly_specific_unmatched_propagates():
    cleaned = make_cleaned_research()
    idx = build_fact_index(cleaned)
    extracted = [_ext("0.987OR", highly=True)]
    stats, warnings = detect_hallucinations(extracted, idx)
    assert stats.highly_specific_count == 1
    assert stats.highly_specific_unmatched == 1
    codes = [w.code for w in warnings]
    assert "highly_specific_unmatched" in codes


def test_highly_specific_matched_does_not_warn():
    """structured_facts に登録された highly_specific は警告対象外 (§10.3)。"""
    cleaned = make_cleaned_research()
    idx = build_fact_index(cleaned)
    # "0.207OR" は fixture の key_numbers に含まれる
    extracted = [_ext("0.207OR", highly=True)]
    stats, warnings = detect_hallucinations(extracted, idx)
    assert stats.highly_specific_unmatched == 0
    assert all(w.code != "highly_specific_unmatched" for w in warnings)


def test_low_match_ratio_warning():
    cleaned = make_cleaned_research()
    idx = build_fact_index(cleaned)
    extracted = [_ext("39.5%")] + [_ext(f"{i}.{i}%") for i in range(1, 5)]  # 1/5 = 20%
    stats, warnings = detect_hallucinations(extracted, idx)
    assert stats.matched_ratio == 0.2
    codes = [w.code for w in warnings]
    assert "low_match_ratio" in codes


def test_empty_extracted_returns_full_match_ratio():
    cleaned = make_cleaned_research()
    idx = build_fact_index(cleaned)
    stats, warnings = detect_hallucinations([], idx)
    assert stats.total == 0
    assert stats.matched_ratio == 1.0
    assert warnings == []


def test_check_needs_review_usage_detects_b_tier_highly_specific_quote():
    """needs_review な fact (B tier x highly_specific) が台本に出ると警告。"""
    cleaned = make_cleaned_research(
        sources=[
            {"title": "B src", "url": "https://x", "domain_score": 30, "domain_tier": "B"},
        ],
        key_numbers=[kn(1, value="0.207", unit="OR", flags=["highly_specific"])] * 5,
    )
    # script.body に 0.207OR が出る
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="t",
        turn_texts=[("A", "0.207OR らしいのだ"), ("B", "ですわ"), ("A", "x"), ("B", "y")],
    )
    script = make_script(segments=_full_segments_with(seg))
    warnings = check_needs_review_usage(script, cleaned)
    assert any(w.code == "needs_review_used" for w in warnings)


def test_check_needs_review_usage_no_warning_when_unused():
    cleaned = make_cleaned_research(
        sources=[
            {"title": "B src", "url": "https://x", "domain_score": 30, "domain_tier": "B"},
        ],
        key_numbers=[kn(1, value="0.207", unit="OR", flags=["highly_specific"])] * 5,
    )
    script = make_script()  # default segments don't mention 0.207OR
    warnings = check_needs_review_usage(script, cleaned)
    assert warnings == []


def _full_segments_with(deep_dive_0):
    """5 segment を成立させる helper。"""
    from tests.phase_d._factories import make_segment as ms

    return [
        ms(segment_type="intro", topic_index=None, title="i"),
        deep_dive_0,
        ms(segment_type="deep_dive", topic_index=1, title="d1"),
        ms(segment_type="deep_dive", topic_index=2, title="d2"),
        ms(segment_type="conclusion", topic_index=None, title="c"),
    ]


def test_extracted_numbers_integrate_with_index():
    """extract_numbers の出力をそのまま detect_hallucinations に流せる。"""
    cleaned = make_cleaned_research()
    idx = build_fact_index(cleaned)
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="t",
        turn_texts=[("A", "39.5%は不足のだ"), ("B", "2.94倍ですわ"), ("A", "x"), ("B", "y")],
    )
    script = make_script(segments=_full_segments_with(seg))
    extracted = extract_numbers(script)
    stats, _ = detect_hallucinations(extracted, idx)
    assert stats.matched >= 2  # 39.5% と 2.94倍
