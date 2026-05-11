"""topic_overlap の単体テスト (backlog §7-B)。

3 topic 間の source_idx 共有率 (Jaccard) が閾値 0.5 を超える場合に
topic_overlap_warning が発出されることを確認する。
"""

from __future__ import annotations

from radio_director.models.show_spec import Claim, ShowSpec, TopicSpec
from radio_director.phase_d.topic_overlap import (
    JACCARD_THRESHOLD,
    check_topic_overlap,
)

from tests.phase_d._factories import make_cleaned_research, make_script, make_segment


def _topic(title: str, source_idxs: list[int]) -> TopicSpec:
    """指定 source_idx を持つ key_claims から TopicSpec を作る。"""
    claims = [
        Claim(text=f"claim-{idx}", source_idx=idx, source_tier="AAA", confidence="medium")
        for idx in source_idxs
    ]
    return TopicSpec(
        title=title, hook=f"hook for {title}", key_claims=claims, tone="解説", estimated_turns=14
    )


def _show_spec_with_topics(topics: list[TopicSpec]) -> ShowSpec:
    return ShowSpec(
        title="テスト番組",
        thumbnail_title="テスト",
        hook="hook",
        angle="angle",
        arc="arc",
        tone="tone",
        topics=topics,
        conclusion_message="まとめ",
    )


def _script_with_topics(topics: list[TopicSpec]):
    """指定 topics 数に対応した segments を構築して Script を作る。

    topic_overlap は script.show_spec.topics だけを読むため、segments は
    Pydantic 制約 (min_length=4, max_length=6) を満たす形で minimum を埋める。
    """
    show = _show_spec_with_topics(topics)
    segments = [make_segment(segment_type="intro", topic_index=None, title="イントロ")]
    for i, t in enumerate(topics):
        segments.append(
            make_segment(segment_type="deep_dive", topic_index=i, title=t.title)
        )
    segments.append(make_segment(segment_type="conclusion", topic_index=None, title="まとめ"))
    return make_script(show_spec=show, segments=segments)


# ---------------------------------------------------------------------------
# 基本ケース: clean / 閾値超過 / 完全重複
# ---------------------------------------------------------------------------


def test_no_overlap_yields_no_warning():
    """3 topic が完全に異なる source_idx を使う場合は警告なし (Jaccard 全ペア 0.0)。"""
    cleaned = make_cleaned_research()
    topics = [
        _topic("t0", [1]),
        _topic("t1", [2]),
        _topic("t2", [3]),
    ]
    warnings = check_topic_overlap(_script_with_topics(topics), cleaned)
    assert warnings == []


def test_full_overlap_triggers_warning():
    """3 topic 全部が同じ source 1 個だけを共有 = Jaccard=1.0 で警告。"""
    cleaned = make_cleaned_research()
    topics = [
        _topic("t0", [1]),
        _topic("t1", [1]),
        _topic("t2", [1]),
    ]
    warnings = check_topic_overlap(_script_with_topics(topics), cleaned)
    assert len(warnings) == 1
    w = warnings[0]
    assert w.code == "topic_overlap_warning"
    assert "Jaccard=1.00" in w.message


def test_jaccard_below_threshold_no_warning():
    """Jaccard=1/3≒0.333 は閾値 0.5 未満で警告なし (実機 2026-05-11 と同等)。"""
    cleaned = make_cleaned_research()
    topics = [
        _topic("t0", [1, 2]),  # {1, 2}
        _topic("t1", [2, 3]),  # {2, 3}  shared={2} union={1,2,3} jaccard=1/3
        _topic("t2", [4]),
    ]
    warnings = check_topic_overlap(_script_with_topics(topics), cleaned)
    assert warnings == []


def _wide_cleaned():
    """5 source 持つ cleaned_research (range filter で source_idx 1-5 を全て残す)。"""
    sources = [
        {"title": f"s{i}", "url": f"https://x.com/{i}", "domain_score": 80, "domain_tier": "AAA"}
        for i in range(1, 6)
    ]
    return make_cleaned_research(sources=sources)


def test_jaccard_at_threshold_does_not_trigger():
    """Jaccard=0.5 ちょうど (境界) は警告しない (厳密な > を使う)。"""
    cleaned = _wide_cleaned()  # source_idx 1-5 が有効
    topics = [
        _topic("t0", [1, 2]),  # {1, 2}
        _topic("t1", [1, 3]),  # {1, 3}  shared={1} union={1,2,3} jaccard=1/3≈0.33
        _topic("t2", [4, 5]),  # 独立
    ]
    warnings = check_topic_overlap(_script_with_topics(topics), cleaned)
    assert warnings == []
    # 確認: 厳密な不等号 > を使っているか
    assert JACCARD_THRESHOLD == 0.5


def test_strict_above_threshold_triggers():
    """Jaccard=0.667 (> 0.5) で確実に警告。"""
    cleaned = make_cleaned_research()
    topics = [
        _topic("t0", [1, 2]),
        _topic("t1", [1, 2, 3]),  # shared={1,2} union={1,2,3} jaccard=2/3
        _topic("t2", [4]),
    ]
    warnings = check_topic_overlap(_script_with_topics(topics), cleaned)
    assert len(warnings) == 1
    assert "Jaccard=0.67" in warnings[0].message


# ---------------------------------------------------------------------------
# 集約: worst pair 1 件のみ
# ---------------------------------------------------------------------------


def test_aggregates_to_single_worst_pair_warning():
    """複数ペアが閾値超過でも、warning は最悪ペア 1 件に集約される。"""
    cleaned = make_cleaned_research()
    topics = [
        _topic("t0", [1, 2]),
        _topic("t1", [1, 2]),  # vs t0: jaccard=1.0
        _topic("t2", [1, 2, 3]),  # vs t0: 2/3=0.67, vs t1: 2/3=0.67
    ]
    warnings = check_topic_overlap(_script_with_topics(topics), cleaned)
    assert len(warnings) == 1
    # worst は t0 x t1 (jaccard=1.0)
    assert "Jaccard=1.00" in warnings[0].message
    assert warnings[0].location == "topic_pair[0_x_1]"


# ---------------------------------------------------------------------------
# 範囲外 source_idx の除外 (レビュー反映)
# ---------------------------------------------------------------------------


def test_out_of_range_source_idx_is_filtered():
    """範囲外 source_idx (citation_normalizer が unknown_source_idx で
    別途扱う) は overlap 集合から除外されるため、false positive を出さない。

    make_cleaned_research() のデフォルト sources は 3 件 (idx 1-3)。
    両 topic が idx=999 (範囲外) のみを共有しても警告は出ない。
    """
    cleaned = make_cleaned_research()  # sources=3 件
    topics = [
        _topic("t0", [999]),  # 範囲外
        _topic("t1", [999]),  # 範囲外
        _topic("t2", [1]),
    ]
    warnings = check_topic_overlap(_script_with_topics(topics), cleaned)
    # 範囲外 source は除外されるので集合は空、警告なし
    assert warnings == []


def test_partial_out_of_range_does_not_inflate_jaccard():
    """範囲外 source_idx を含む topic は、その範囲外分が除外されて評価される。"""
    cleaned = make_cleaned_research()  # sources=3 件
    topics = [
        _topic("t0", [1, 999]),  # 範囲内={1}, 999 は除外
        _topic("t1", [1, 888]),  # 範囲内={1}, 888 は除外
        _topic("t2", [2]),
    ]
    warnings = check_topic_overlap(_script_with_topics(topics), cleaned)
    # t0 と t1 はそれぞれ {1} だけになり Jaccard=1.0 で警告 (これは正当な真の重複)
    assert len(warnings) == 1
    assert "Jaccard=1.00" in warnings[0].message


# ---------------------------------------------------------------------------
# topic 件数のエッジケース (min=2, max=4)
# ---------------------------------------------------------------------------


def test_two_topics_with_full_overlap_triggers_warning():
    """topics=2 (1 ペア) でも閾値超過なら警告。"""
    cleaned = make_cleaned_research()
    topics = [
        _topic("t0", [1, 2]),
        _topic("t1", [1, 2]),
    ]
    warnings = check_topic_overlap(_script_with_topics(topics), cleaned)
    assert len(warnings) == 1


def test_four_topics_evaluates_all_pairs():
    """topics=4 で 4C2=6 ペアを評価、最悪ペアが warning となる。"""
    cleaned = make_cleaned_research()
    topics = [
        _topic("t0", [1]),
        _topic("t1", [2]),
        _topic("t2", [3]),
        _topic("t3", [3]),  # vs t2: Jaccard=1.0 (最悪)
    ]
    warnings = check_topic_overlap(_script_with_topics(topics), cleaned)
    assert len(warnings) == 1
    assert warnings[0].location == "topic_pair[2_x_3]"
