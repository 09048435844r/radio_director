"""Phase A の出力スキーマ。Phase B が消費する形式。

source_idx を domain_tier に解決し、highly_specific フラグから
needs_review を導出した ResolvedFact を保持する。
QualityReport を埋め込みで持つことで、呼び出し側は単一オブジェクトとして
扱える (radio_director_design.md §16 のタプル返しを単純化)。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from radio_director.models.research_brief import (
    Confidence,
    Controversy,
    DomainTier,
    ResearchSource,
)

FactCategory = Literal["key_numbers", "key_entities", "surprising_claims"]
QualityWarningCode = Literal[
    "low_key_numbers",
    "low_high_medium_ratio",
    "low_tier_ratio",
    "needs_review_fact",
]
OverallQuality = Literal["sufficient", "warning", "insufficient"]


class ResolvedFact(BaseModel):
    """source_idx を domain_tier に解決し warning フラグを導出した最小単位。"""

    category: FactCategory
    text: str
    source_idx: int
    primary_source_tier: DomainTier
    cross_validated_sources: list[int]
    confidence: Confidence
    flags: list[str]
    needs_review: bool
    raw: dict[str, Any]


class CleanedFacts(BaseModel):
    key_numbers: list[ResolvedFact] = Field(default_factory=list)
    key_entities: list[ResolvedFact] = Field(default_factory=list)
    surprising_claims: list[ResolvedFact] = Field(default_factory=list)
    controversies: list[Controversy] = Field(default_factory=list)


class QualityWarning(BaseModel):
    code: QualityWarningCode
    message: str
    metric: float


class QualityReport(BaseModel):
    overall_quality: OverallQuality
    metrics: dict[str, float]
    warnings: list[QualityWarning] = Field(default_factory=list)


class CleanedResearch(BaseModel):
    theme: str
    angle: str
    research_mode: str
    research_content: str
    queries: list[str]
    sources: list[ResearchSource]
    facts: CleanedFacts
    quality_report: QualityReport
