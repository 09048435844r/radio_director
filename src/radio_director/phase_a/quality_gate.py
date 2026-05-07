"""Phase A の品質ゲート。

判定基準は radio_director_design.md §21 に準拠:
  1. key_numbers 件数 >= 5
  2. confidence high+medium 比率 >= 80%
  3. domain_tier AAA/AA/A 比率 >= 50%
  4. needs_review (highly_specific + tier=B) を含むかの伝播

設計判断:
  - key_numbers == 0 のみハードに失敗 (InsufficientResearchError)
  - 他は警告ログとして QualityReport に積み、続行
"""

from __future__ import annotations

from radio_director.models.cleaned_research import (
    CleanedFacts,
    QualityReport,
    QualityWarning,
)
from radio_director.models.research_brief import ResearchBrief

KEY_NUMBERS_MIN_OK = 5
HIGH_MEDIUM_RATIO_MIN = 0.80
TOP_TIER_RATIO_MIN = 0.50


class InsufficientResearchError(Exception):
    """key_numbers が 0 件。再リサーチを推奨してハードに失敗させる。"""


def run_quality_gate(brief: ResearchBrief, facts: CleanedFacts) -> QualityReport:
    kn_count = len(facts.key_numbers)
    if kn_count == 0:
        raise InsufficientResearchError(
            "key_numbers が 0 件です。再リサーチを推奨します。"
        )

    all_facts = facts.key_numbers + facts.key_entities + facts.surprising_claims
    total = len(all_facts)
    high_medium = sum(1 for f in all_facts if f.confidence in ("high", "medium"))
    hm_ratio = high_medium / total if total else 0.0

    sources = brief.research_sources
    top_tier = sum(1 for s in sources if s.domain_tier in ("AAA", "AA", "A"))
    tier_ratio = top_tier / len(sources) if sources else 0.0

    needs_review_count = sum(1 for f in all_facts if f.needs_review)

    warnings: list[QualityWarning] = []
    if kn_count < KEY_NUMBERS_MIN_OK:
        warnings.append(
            QualityWarning(
                code="low_key_numbers",
                message=(
                    f"key_numbers が {kn_count} 件 "
                    f"(最低 {KEY_NUMBERS_MIN_OK} 件推奨)"
                ),
                metric=float(kn_count),
            )
        )
    if hm_ratio < HIGH_MEDIUM_RATIO_MIN:
        warnings.append(
            QualityWarning(
                code="low_high_medium_ratio",
                message=(
                    f"confidence high+medium 比率 {hm_ratio:.1%} "
                    f"(推奨 {HIGH_MEDIUM_RATIO_MIN:.0%} 以上)"
                ),
                metric=hm_ratio,
            )
        )
    if tier_ratio < TOP_TIER_RATIO_MIN:
        warnings.append(
            QualityWarning(
                code="low_tier_ratio",
                message=(
                    f"AAA/AA/A tier 比率 {tier_ratio:.1%} "
                    f"(推奨 {TOP_TIER_RATIO_MIN:.0%} 以上)"
                ),
                metric=tier_ratio,
            )
        )
    if needs_review_count:
        warnings.append(
            QualityWarning(
                code="needs_review_fact",
                message=(
                    f"highly_specific フラグ + B tier の fact が "
                    f"{needs_review_count} 件 (要手動確認)"
                ),
                metric=float(needs_review_count),
            )
        )

    overall = "sufficient" if not warnings else "warning"

    return QualityReport(
        overall_quality=overall,
        metrics={
            "key_numbers_count": float(kn_count),
            "high_medium_ratio": hm_ratio,
            "top_tier_ratio": tier_ratio,
            "needs_review_count": float(needs_review_count),
        },
        warnings=warnings,
    )
