"""verifier (オーケストレーション) の end-to-end ユニット。"""

from __future__ import annotations

import json

from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_d.verifier import verify

from tests.phase_d._factories import (
    make_cleaned_research,
    make_script,
    make_segment,
)


class FakeLLMClient(LLMClient):
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def generate(self, prompt, *, temperature=0.5, max_tokens=1024, json_mode=True):
        self.calls += 1
        return self.response


_METADATA_RESPONSE = json.dumps(
    {
        "title": "テスト動画",
        "description": "概要." * 30,
        "hashtags": ["a", "b", "c", "d", "e"],
    },
    ensure_ascii=False,
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


def test_verify_assembles_verified_script():
    cleaned = make_cleaned_research()
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="d0",
        turn_texts=[
            ("A", "39.5%は不足のだ [AAA]"),
            ("B", "2.94倍ですわ [src=1][AAA]"),
            ("A", "x"),
            ("B", "y"),
        ],
    )
    script = make_script(segments=_full_segments_with(seg))
    client = FakeLLMClient(_METADATA_RESPONSE)

    verified = verify(script, cleaned, client=client)
    assert verified.metadata.title == "テスト動画"
    assert verified.metrics.total_numbers_extracted >= 2
    assert verified.metrics.matched_to_structured_facts >= 2
    assert verified.metrics.citation_tags_total >= 2
    assert client.calls == 1


def test_verify_propagates_unmatched_warnings():
    cleaned = make_cleaned_research()
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="d0",
        turn_texts=[
            ("A", "999.9% も上昇 [AAA]"),
            ("B", "ですわ"),
            ("A", "x"),
            ("B", "y"),
        ],
    )
    script = make_script(segments=_full_segments_with(seg))
    client = FakeLLMClient(_METADATA_RESPONSE)

    verified = verify(script, cleaned, client=client)
    codes = [w.code for w in verified.warnings]
    assert "unmatched_number" in codes


def test_verify_propagates_tier_mismatch():
    """src=3 (B tier) なのに台本で [src=3][AAA] と書かれている場合。"""
    cleaned = make_cleaned_research()
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="d0",
        turn_texts=[
            ("A", "事実 [src=3][AAA]"),
            ("B", "ですわ"),
            ("A", "x"),
            ("B", "y"),
        ],
    )
    script = make_script(segments=_full_segments_with(seg))
    client = FakeLLMClient(_METADATA_RESPONSE)

    verified = verify(script, cleaned, client=client)
    codes = [w.code for w in verified.warnings]
    assert "tier_mismatch" in codes
    assert verified.metrics.citation_tags_inconsistent >= 1


def test_verify_metrics_chapter_count():
    cleaned = make_cleaned_research()
    script = make_script()
    client = FakeLLMClient(_METADATA_RESPONSE)

    verified = verify(script, cleaned, client=client)
    assert len(verified.metadata.chapters) == len(script.segments)


def test_verify_propagates_character_warnings():
    """backlog §8: speaker=B が「のだ」語尾を使った場合、verify() の集約 warnings に含まれる。"""
    cleaned = make_cleaned_research()
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="d0",
        turn_texts=[
            ("A", "驚きなのだ"),
            ("B", "それは興味深いのだ"),  # 致命的: B が A 語尾
            ("A", "x"),
            ("B", "y"),
        ],
    )
    script = make_script(segments=_full_segments_with(seg))
    client = FakeLLMClient(_METADATA_RESPONSE)

    verified = verify(script, cleaned, client=client)
    codes = [w.code for w in verified.warnings]
    assert "wrong_speaker_voice" in codes


def test_verify_propagates_topic_overlap_warning():
    """backlog §7-B: 3 topic が同一 source_idx ばかりを共有する場合に
    verify() の集約 warnings に topic_overlap_warning が含まれる。"""
    from radio_director.models.show_spec import Claim, ShowSpec, TopicSpec

    cleaned = make_cleaned_research()
    # 全 3 topic が source_idx=1 のみを共有 (Jaccard=1.0、病的重複)
    overlap_topics = [
        TopicSpec(
            title=f"t{i}",
            hook="hook",
            key_claims=[
                Claim(text=f"c{i}", source_idx=1, source_tier="AAA", confidence="medium")
            ],
            tone="解説",
            estimated_turns=14,
        )
        for i in range(3)
    ]
    show = ShowSpec(
        title="テスト",
        thumbnail_title="テスト",
        hook="hook",
        angle="angle",
        arc="arc",
        tone="tone",
        topics=overlap_topics,
        conclusion_message="まとめ",
    )
    script = make_script(show_spec=show)
    client = FakeLLMClient(_METADATA_RESPONSE)

    verified = verify(script, cleaned, client=client)
    codes = [w.code for w in verified.warnings]
    assert "topic_overlap_warning" in codes
