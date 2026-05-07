"""quality_gate.run_quality_gate の単体テスト。"""

from __future__ import annotations

import pytest

from radio_director.models.research_brief import ResearchBrief
from radio_director.phase_a.decoder import decode
from radio_director.phase_a.quality_gate import (
    HIGH_MEDIUM_RATIO_MIN,
    KEY_NUMBERS_MIN_OK,
    InsufficientResearchError,
)

from tests.phase_a._factories import kn, make_brief


def _decode(payload):
    return decode(ResearchBrief.model_validate(payload))


def test_zero_key_numbers_raises():
    payload = make_brief(key_numbers=[])
    with pytest.raises(InsufficientResearchError):
        _decode(payload)


def test_below_min_key_numbers_warns_but_passes():
    """KEY_NUMBERS_MIN_OK 未満 (1〜4 件) は警告 + 続行。"""
    payload = make_brief(key_numbers=[kn(1)] * (KEY_NUMBERS_MIN_OK - 1))
    cleaned = _decode(payload)
    codes = [w.code for w in cleaned.quality_report.warnings]
    assert "low_key_numbers" in codes
    assert cleaned.quality_report.overall_quality == "warning"


def test_at_min_key_numbers_does_not_warn():
    payload = make_brief(key_numbers=[kn(1)] * KEY_NUMBERS_MIN_OK)
    cleaned = _decode(payload)
    codes = [w.code for w in cleaned.quality_report.warnings]
    assert "low_key_numbers" not in codes


def test_high_medium_ratio_threshold_just_below():
    """5件中 1件だけ low (20%) -> high_medium=80% で境界通過。"""
    payload = make_brief(
        key_numbers=[kn(1, confidence="medium")] * 4 + [kn(1, confidence="low")],
    )
    cleaned = _decode(payload)
    codes = [w.code for w in cleaned.quality_report.warnings]
    assert cleaned.quality_report.metrics["high_medium_ratio"] == pytest.approx(0.8)
    assert "low_high_medium_ratio" not in codes


def test_high_medium_ratio_below_threshold_warns():
    """5件中 2件 low -> 60% < 80% で警告。"""
    payload = make_brief(
        key_numbers=[kn(1, confidence="medium")] * 3 + [kn(1, confidence="low")] * 2,
    )
    cleaned = _decode(payload)
    codes = [w.code for w in cleaned.quality_report.warnings]
    assert "low_high_medium_ratio" in codes
    assert cleaned.quality_report.metrics["high_medium_ratio"] < HIGH_MEDIUM_RATIO_MIN


def test_low_tier_ratio_warns():
    """sources が全て B tier -> 0% で警告。"""
    payload = make_brief(
        sources=[
            {
                "title": f"B{i}",
                "url": f"https://x{i}",
                "domain_score": 30,
                "domain_tier": "B",
            }
            for i in range(3)
        ],
        key_numbers=[kn(1)] * 5,
    )
    cleaned = _decode(payload)
    codes = [w.code for w in cleaned.quality_report.warnings]
    assert "low_tier_ratio" in codes
    assert cleaned.quality_report.metrics["top_tier_ratio"] == 0.0


def test_needs_review_warning_propagates():
    payload = make_brief(
        sources=[
            {
                "title": "B",
                "url": "https://x",
                "domain_score": 30,
                "domain_tier": "B",
            },
        ],
        key_numbers=[kn(1, flags=["highly_specific"])] * 5,
    )
    cleaned = _decode(payload)
    codes = [w.code for w in cleaned.quality_report.warnings]
    assert "needs_review_fact" in codes
    assert cleaned.quality_report.metrics["needs_review_count"] == 5.0


def test_sufficient_when_all_thresholds_met():
    payload = make_brief(
        key_numbers=[kn(1, confidence="high")] * 5,
    )
    cleaned = _decode(payload)
    assert cleaned.quality_report.overall_quality == "sufficient"
    assert cleaned.quality_report.warnings == []
