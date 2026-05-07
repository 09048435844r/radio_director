"""実機 v1.6 research_brief.json での統合テスト。

interface_spec.md §3.3.3 / radio_director_design.md §21 の実測値に紐付け。
データソース: research_pipeline 2026-05-07 23:00:40 スモークテスト
(テーマ「睡眠と免疫」、44 sources / 116 fact / highly_specific 2件)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from radio_director.models.research_brief import ResearchBrief
from radio_director.phase_a.decoder import decode

SAMPLE_PATH = Path(__file__).parent.parent / "data" / "research_brief_sample.json"


@pytest.fixture(scope="module")
def cleaned():
    payload = SAMPLE_PATH.read_text(encoding="utf-8")
    brief = ResearchBrief.model_validate_json(payload)
    return decode(brief)


def test_fact_counts_match_v16_smoke(cleaned):
    """§3.3.3 / §21 の実測値: 34 / 77 / 5 / 0。"""
    assert len(cleaned.facts.key_numbers) == 34
    assert len(cleaned.facts.key_entities) == 77
    assert len(cleaned.facts.surprising_claims) == 5
    assert len(cleaned.facts.controversies) == 0


def test_source_count_and_tiers(cleaned):
    """§3.3.3: 44 sources / AAA=23 / A=2 / B=19。"""
    assert len(cleaned.sources) == 44
    tiers = [s.domain_tier for s in cleaned.sources]
    assert tiers.count("AAA") == 23
    assert tiers.count("A") == 2
    assert tiers.count("B") == 19


def test_highly_specific_flags_are_aaa_so_no_review_needed(cleaned):
    """§21: 2件の highly_specific は両方 nature.com (AAA) のため許容。"""
    flagged = [
        f for f in cleaned.facts.key_numbers if "highly_specific" in f.flags
    ]
    assert len(flagged) == 2
    assert all(f.primary_source_tier == "AAA" for f in flagged)
    assert all(f.needs_review is False for f in flagged)


def test_quality_gate_passes_with_sufficient_status(cleaned):
    """§21: 全条件クリアで sufficient。"""
    assert cleaned.quality_report.overall_quality == "sufficient"
    assert cleaned.quality_report.warnings == []


def test_metrics_match_expected(cleaned):
    """§3.3.3: high=3 + medium=113 / low=0 -> hm_ratio=1.0、tier_ratio=25/44。"""
    metrics = cleaned.quality_report.metrics
    assert metrics["key_numbers_count"] == 34.0
    assert metrics["high_medium_ratio"] == pytest.approx(1.0)
    assert metrics["top_tier_ratio"] == pytest.approx(25 / 44)
    assert metrics["needs_review_count"] == 0.0


def test_angle_and_research_content_pass_through(cleaned):
    """angle と research_content が下流フェーズに伝播していること。"""
    assert "睡眠" in cleaned.angle
    assert len(cleaned.research_content) > 30000  # 実測 38,567 字
