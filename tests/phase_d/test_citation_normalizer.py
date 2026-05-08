"""citation_normalizer の単体テスト。"""

from __future__ import annotations

from radio_director.phase_d.citation_normalizer import normalize_citations

from tests.phase_d._factories import (
    make_cleaned_research,
    make_script,
    make_segment,
)


def _full_segments_with(deep_dive_0):
    from tests.phase_d._factories import make_segment as ms

    return [
        ms(segment_type="intro", topic_index=None, title="i"),
        deep_dive_0,
        ms(segment_type="deep_dive", topic_index=1, title="d1"),
        ms(segment_type="deep_dive", topic_index=2, title="d2"),
        ms(segment_type="conclusion", topic_index=None, title="c"),
    ]


def _scan(turn_texts: list[tuple[str, str]]):
    cleaned = make_cleaned_research()  # 3 sources: AAA / AAA / B
    seg = make_segment(
        segment_type="deep_dive", topic_index=0, title="t", turn_texts=turn_texts
    )
    script = make_script(segments=_full_segments_with(seg))
    return normalize_citations(script, cleaned)


def test_tier_only_canonical():
    findings, warnings = _scan(
        [("A", "事実だね [AAA]"), ("B", "ですわ"), ("A", "x"), ("B", "y")]
    )
    assert any(f.canonical == "[AAA]" for f in findings)
    assert all(w.code != "tier_mismatch" for w in warnings)


def test_src_then_tier_canonicalizes_to_full_form():
    findings, _ = _scan(
        [("A", "事実 [1][AAA]"), ("B", "ですわ"), ("A", "x"), ("B", "y")]
    )
    full = [f for f in findings if f.canonical == "[src=1][AAA]"]
    assert len(full) == 1
    assert full[0].raw == "[1][AAA]"


def test_full_tag_with_confidence_drops_confidence():
    findings, _ = _scan(
        [("A", "事実 [src=2][AAA][medium]"), ("B", "ですわ"), ("A", "x"), ("B", "y")]
    )
    full = [f for f in findings if f.canonical == "[src=2][AAA]"]
    assert len(full) == 1


def test_tier_mismatch_warning():
    """src=3 は B tier だが script で [AAA] と書かれている → tier_mismatch。"""
    findings, warnings = _scan(
        [("A", "[src=3][AAA] らしい"), ("B", "ですわ"), ("A", "x"), ("B", "y")]
    )
    codes = [w.code for w in warnings]
    assert "tier_mismatch" in codes
    assert any(not f.is_consistent and f.source_idx == 3 for f in findings)


def test_unknown_source_idx_warning():
    findings, warnings = _scan(
        [("A", "[src=99][AAA] らしい"), ("B", "ですわ"), ("A", "x"), ("B", "y")]
    )
    codes = [w.code for w in warnings]
    assert "unknown_source_idx" in codes
    assert any(not f.is_consistent for f in findings)


def test_consistent_full_tag_no_warning():
    """src=1 は AAA tier、script でも [AAA] → 一致。"""
    findings, warnings = _scan(
        [("A", "[src=1][AAA] らしい"), ("B", "ですわ"), ("A", "x"), ("B", "y")]
    )
    full = [f for f in findings if f.source_idx == 1]
    assert full and full[0].is_consistent
    assert all(w.code not in ("tier_mismatch", "unknown_source_idx") for w in warnings)


def test_empty_text_yields_no_findings():
    findings, warnings = _scan(
        [("A", "出典なし"), ("B", "ですわ"), ("A", "x"), ("B", "y")]
    )
    assert findings == []
    assert warnings == []


def test_multiple_tags_in_one_turn():
    findings, _ = _scan(
        [
            ("A", "[AAA] と [src=2][AAA] 両方"),
            ("B", "ですわ"),
            ("A", "x"),
            ("B", "y"),
        ]
    )
    canons = [f.canonical for f in findings]
    assert "[AAA]" in canons
    assert "[src=2][AAA]" in canons
