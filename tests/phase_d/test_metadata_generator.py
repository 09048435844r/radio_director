"""metadata_generator の単体テスト (FakeLLMClient で LLM 差し替え)。"""

from __future__ import annotations

import json

import pytest

from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_d.metadata_generator import (
    MetadataGenerationError,
    SECONDS_PER_TURN,
    build_chapters,
    generate_metadata,
)

from tests.phase_d._factories import make_script


class FakeLLMClient(LLMClient):
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def generate(self, prompt, *, temperature=0.5, max_tokens=1024, json_mode=True):
        self.calls += 1
        return self.response


_VALID_PAYLOAD = json.dumps(
    {
        "title": "睡眠と免疫の最新科学",
        "description": "睡眠と免疫について 3 つの観点で深掘り。"
        + "知って明日から役立つ実践情報を凝縮しました。" * 4,
        "hashtags": ["#睡眠", "免疫", "健康", "科学", "ラジオ"],
    },
    ensure_ascii=False,
)


def test_generates_valid_metadata():
    script = make_script()
    client = FakeLLMClient(_VALID_PAYLOAD)
    md = generate_metadata(script, client=client)
    assert md.title == "睡眠と免疫の最新科学"
    assert "#睡眠" not in md.hashtags  # 頭の # は除去される
    assert "睡眠" in md.hashtags
    assert len(md.hashtags) == 5
    assert client.calls == 1


def test_chapters_count_matches_segments():
    script = make_script()
    client = FakeLLMClient(_VALID_PAYLOAD)
    md = generate_metadata(script, client=client)
    assert len(md.chapters) == len(script.segments)


def test_chapters_timestamps_are_cumulative():
    script = make_script()
    chapters = build_chapters(script)
    # intro = 0:00、deep_dive_0 は intro の turn 数 (4) × 5 秒 = 20 秒 = 0:20
    assert chapters[0].timestamp == "00:00"
    assert chapters[1].timestamp == f"00:{4 * SECONDS_PER_TURN:02d}"


def test_chapter_titles_resolve_from_show_spec():
    script = make_script()
    chapters = build_chapters(script)
    titles = [c.title for c in chapters]
    assert titles[0] == "イントロ"
    assert titles[-1] == "まとめ"
    for i, t in enumerate(titles[1:-1]):
        assert t == script.show_spec.topics[i].title


def test_invalid_json_raises():
    script = make_script()
    client = FakeLLMClient("これは JSON じゃない")
    with pytest.raises(MetadataGenerationError):
        generate_metadata(script, client=client)


def test_missing_required_key_raises():
    script = make_script()
    payload = json.dumps({"title": "x", "description": "y" * 60})  # hashtags 欠落
    client = FakeLLMClient(payload)
    with pytest.raises(MetadataGenerationError):
        generate_metadata(script, client=client)


def test_too_short_description_raises():
    """description min_length=50 違反 → MetadataGenerationError。"""
    script = make_script()
    payload = json.dumps(
        {"title": "x", "description": "短い", "hashtags": ["a", "b", "c"]},
        ensure_ascii=False,
    )
    client = FakeLLMClient(payload)
    with pytest.raises(MetadataGenerationError):
        generate_metadata(script, client=client)


def test_strips_code_fences_in_response():
    script = make_script()
    raw = "```json\n" + _VALID_PAYLOAD + "\n```"
    client = FakeLLMClient(raw)
    md = generate_metadata(script, client=client)
    assert md.title


def test_strips_think_tags_in_response():
    script = make_script()
    raw = "<think>let me plan</think>\n" + _VALID_PAYLOAD
    client = FakeLLMClient(raw)
    md = generate_metadata(script, client=client)
    assert md.title


def test_references_empty_when_no_findings_provided():
    """citation_findings 未指定時は references=[] (後方互換)。"""
    script = make_script()
    client = FakeLLMClient(_VALID_PAYLOAD)
    md = generate_metadata(script, client=client)
    assert md.references == []


def test_references_resolved_from_citation_findings():
    """is_consistent=True の source_idx のみが SourceRef にマップされる。"""
    from radio_director.phase_d.citation_normalizer import CitationFinding
    from tests.phase_d._factories import make_cleaned_research

    cleaned = make_cleaned_research()  # 3 sources: AAA / AAA / B
    findings = [
        CitationFinding(
            raw="[src=1][AAA]",
            canonical="[src=1][AAA]",
            source_idx=1,
            tier="AAA",
            is_consistent=True,
            location="deep_dive_0",
        ),
        CitationFinding(
            raw="[src=3][B]",
            canonical="[src=3][B]",
            source_idx=3,
            tier="B",
            is_consistent=True,
            location="deep_dive_1",
        ),
    ]
    script = make_script()
    client = FakeLLMClient(_VALID_PAYLOAD)
    md = generate_metadata(
        script, cleaned, findings, client=client
    )
    assert len(md.references) == 2
    assert md.references[0].tier == "AAA"
    assert md.references[1].tier == "B"


def test_references_dedup_by_url():
    """同じ source_idx を複数回引用しても references には 1 件のみ。"""
    from radio_director.phase_d.citation_normalizer import CitationFinding
    from tests.phase_d._factories import make_cleaned_research

    cleaned = make_cleaned_research()
    findings = [
        CitationFinding(
            raw="[src=1][AAA]", canonical="[src=1][AAA]", source_idx=1,
            tier="AAA", is_consistent=True, location="deep_dive_0",
        ),
        CitationFinding(
            raw="[src=1][AAA]", canonical="[src=1][AAA]", source_idx=1,
            tier="AAA", is_consistent=True, location="deep_dive_1",
        ),
    ]
    script = make_script()
    client = FakeLLMClient(_VALID_PAYLOAD)
    md = generate_metadata(script, cleaned, findings, client=client)
    assert len(md.references) == 1


def test_references_skip_inconsistent_findings():
    """is_consistent=False (tier_mismatch / unknown_source_idx) は無視。"""
    from radio_director.phase_d.citation_normalizer import CitationFinding
    from tests.phase_d._factories import make_cleaned_research

    cleaned = make_cleaned_research()
    findings = [
        CitationFinding(
            raw="[src=1][AAA]", canonical="[src=1][AAA]", source_idx=1,
            tier="AAA", is_consistent=True, location="deep_dive_0",
        ),
        CitationFinding(
            raw="[src=99][AAA]", canonical="[src=99][AAA]", source_idx=99,
            tier="AAA", is_consistent=False, location="deep_dive_1",
        ),
    ]
    script = make_script()
    client = FakeLLMClient(_VALID_PAYLOAD)
    md = generate_metadata(script, cleaned, findings, client=client)
    assert len(md.references) == 1
    assert md.references[0].tier == "AAA"


def test_references_skip_tier_only_findings():
    """source_idx=None の tier-only タグは references 候補にならない。"""
    from radio_director.phase_d.citation_normalizer import CitationFinding
    from tests.phase_d._factories import make_cleaned_research

    cleaned = make_cleaned_research()
    findings = [
        CitationFinding(
            raw="[AAA]", canonical="[AAA]", source_idx=None,
            tier="AAA", is_consistent=True, location="deep_dive_0",
        ),
    ]
    script = make_script()
    client = FakeLLMClient(_VALID_PAYLOAD)
    md = generate_metadata(script, cleaned, findings, client=client)
    assert md.references == []


def test_references_zero_findings_yields_empty_list():
    """findings が空 list でも references=[] で正常完了。"""
    from tests.phase_d._factories import make_cleaned_research

    cleaned = make_cleaned_research()
    script = make_script()
    client = FakeLLMClient(_VALID_PAYLOAD)
    md = generate_metadata(script, cleaned, [], client=client)
    assert md.references == []


def test_references_invalid_url_skipped():
    """cleaned_research.sources の URL が不正なら HttpUrl 検証で skip される。"""
    from radio_director.phase_d.citation_normalizer import CitationFinding
    from tests.phase_d._factories import make_cleaned_research

    cleaned = make_cleaned_research(
        sources=[
            {
                "title": "bad url",
                "url": "not-a-url",  # HttpUrl 検証で弾かれる
                "domain_score": 90,
                "domain_tier": "AAA",
            },
        ],
    )
    findings = [
        CitationFinding(
            raw="[src=1][AAA]", canonical="[src=1][AAA]", source_idx=1,
            tier="AAA", is_consistent=True, location="deep_dive_0",
        ),
    ]
    script = make_script()
    client = FakeLLMClient(_VALID_PAYLOAD)
    md = generate_metadata(script, cleaned, findings, client=client)
    assert md.references == []


def test_thumbnail_title_propagated_from_show_spec():
    """ShowSpec.thumbnail_title が VideoMetadata.thumbnail_title に
    機械的にコピーされる (LLM 経由ではない)。"""
    script = make_script()
    client = FakeLLMClient(_VALID_PAYLOAD)
    md = generate_metadata(script, client=client)
    assert md.thumbnail_title == script.show_spec.thumbnail_title


def test_long_episode_uses_hms_format():
    """1 時間超の chapters が HH:MM:SS 形式になること。"""
    from radio_director.models.script import (
        DialogTurn,
        Script,
        ScriptSegment,
        SegmentMetrics,
    )

    base = make_script()
    # 各 segment に大量の turn を持たせ、累積で 1 時間を超えさせる
    big_turns = [
        DialogTurn(speaker="A" if i % 2 == 0 else "B", text=f"{i}")
        for i in range(800)
    ]
    big_script = Script(
        show_spec=base.show_spec,
        segments=[
            ScriptSegment(
                segment_type="intro", topic_index=None, title="i", turns=big_turns
            ),
            ScriptSegment(
                segment_type="deep_dive",
                topic_index=0,
                title="d0",
                turns=big_turns,
            ),
            ScriptSegment(
                segment_type="deep_dive",
                topic_index=1,
                title="d1",
                turns=big_turns[:4],
            ),
            ScriptSegment(
                segment_type="deep_dive",
                topic_index=2,
                title="d2",
                turns=big_turns[:4],
            ),
            ScriptSegment(
                segment_type="conclusion",
                topic_index=None,
                title="c",
                turns=big_turns[:4],
            ),
        ],
        metrics=base.metrics,
    )
    chapters = build_chapters(big_script)
    # deep_dive_0 は intro 直後 = 800 * 5 = 4000 秒 = 1:06:40
    assert ":" in chapters[1].timestamp
    h, m, s = chapters[1].timestamp.split(":")
    assert int(h) >= 1


# ---------------------------------------------------------------------------
# retry 動作テスト (max_attempts=2、Phase B 形式の inline retry)
# ---------------------------------------------------------------------------


class _SequentialMockClient(LLMClient):
    """呼び出し順に異なる response を返す mock client。

    retry テスト用: 1 回目に broken response、2 回目に正常 response を
    返して retry の recovery 経路を検証する。
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate(self, prompt, *, temperature=0.5, max_tokens=1024, json_mode=True):
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[idx]


_INVALID_TITLE_TYPE_PAYLOAD = json.dumps(
    {
        "title": 500,  # int を返す本番再発バグ (2026-05-10)
        "description": "本番で観測された title 型不安定の再現。"
        + "retry で正常 response に切り替わって成功するシナリオ。" * 3,
        "hashtags": ["睡眠", "免疫", "健康", "科学", "ラジオ"],
    },
    ensure_ascii=False,
)

_BROKEN_JSON_PAYLOAD = "これは JSON じゃない、{ 構文も壊れてる"


def test_retry_recovers_from_invalid_title_type():
    """1 回目に title=int (本番再現)、2 回目に正常 → 成功。"""
    script = make_script()
    client = _SequentialMockClient([_INVALID_TITLE_TYPE_PAYLOAD, _VALID_PAYLOAD])
    md = generate_metadata(script, client=client)
    assert md.title == "睡眠と免疫の最新科学"
    assert client.calls == 2


def test_retry_recovers_from_json_parse_error():
    """1 回目に broken JSON、2 回目に正常 → 成功。"""
    script = make_script()
    client = _SequentialMockClient([_BROKEN_JSON_PAYLOAD, _VALID_PAYLOAD])
    md = generate_metadata(script, client=client)
    assert md.title == "睡眠と免疫の最新科学"
    assert client.calls == 2


def test_retry_exhausts_and_raises():
    """2 回とも broken → MetadataGenerationError 伝播 (現状動作の保持)。"""
    script = make_script()
    client = _SequentialMockClient([_BROKEN_JSON_PAYLOAD, _BROKEN_JSON_PAYLOAD])
    with pytest.raises(MetadataGenerationError):
        generate_metadata(script, client=client)
    assert client.calls == 2
