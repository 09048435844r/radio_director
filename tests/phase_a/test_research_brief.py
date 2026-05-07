"""入力スキーマ ResearchBrief の単体テスト。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from radio_director.models.research_brief import ResearchBrief

from tests.phase_a._factories import kn, make_brief


def test_validates_v16_payload():
    brief = ResearchBrief.model_validate(make_brief())
    assert brief.theme == "テストテーマ"
    assert brief.angle == "テスト用 angle"
    assert len(brief.research_sources) == 2
    assert len(brief.structured_facts.key_numbers) == 5


def test_v15_inputs_get_v16_defaults():
    """v1.5 形式 (confidence/cvs/flags なし) でも fallback が当たること。"""
    legacy_kn = {
        "value": "10",
        "unit": "%",
        "context": "ctx",
        "source_idx": 1,
    }
    brief = ResearchBrief.model_validate(
        make_brief(key_numbers=[legacy_kn])
    )
    fact = brief.structured_facts.key_numbers[0]
    assert fact.confidence == "medium"
    assert fact.cross_validated_sources == []
    assert fact.flags == []


def test_extra_top_level_fields_are_ignored():
    """curated_topics などの top-level 拡張は無視 (extra='ignore')。"""
    payload = make_brief(
        extras={
            "curated_topics": [{"foo": "bar"}],
            "perplexity_usage": {"tokens": 100},
            "pipeline_metadata": {"version": "1.6"},
        }
    )
    brief = ResearchBrief.model_validate(payload)
    assert not hasattr(brief, "curated_topics")


def test_missing_required_field_raises():
    payload = make_brief()
    payload.pop("angle")
    with pytest.raises(ValidationError):
        ResearchBrief.model_validate(payload)


def test_invalid_domain_tier_raises():
    bad = make_brief(
        sources=[
            {
                "title": "x",
                "url": "https://x",
                "domain_score": 0,
                "domain_tier": "Z",  # 不正
            }
        ],
        key_numbers=[kn(1)],
    )
    with pytest.raises(ValidationError):
        ResearchBrief.model_validate(bad)


def test_invalid_confidence_raises():
    bad = make_brief(key_numbers=[kn(1, confidence="unknown")])
    with pytest.raises(ValidationError):
        ResearchBrief.model_validate(bad)
