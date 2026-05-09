"""ResearchBrief -> CleanedResearch のデコーダ。

決定論的処理。LLM・外部 API は使わない。
source_idx を 1-based として扱い、各 fact に primary_source_tier と
needs_review フラグを付与する。
"""

from __future__ import annotations

import logging

from radio_director.models.cleaned_research import (
    CleanedFacts,
    CleanedResearch,
    FactCategory,
    ResolvedFact,
)
from radio_director.models.research_brief import (
    DomainTier,
    KeyEntity,
    KeyNumber,
    ResearchBrief,
    SurprisingClaim,
)
from radio_director.phase_a.quality_gate import run_quality_gate

logger = logging.getLogger(__name__)

_FACT_TYPES = (KeyNumber, KeyEntity, SurprisingClaim)
_AnyFact = KeyNumber | KeyEntity | SurprisingClaim


def decode(brief: ResearchBrief) -> CleanedResearch:
    """ResearchBrief を CleanedResearch に変換し品質ゲートを実行する。"""
    tier_map = _build_tier_map(brief)

    cleaned_facts = CleanedFacts(
        key_numbers=[
            _resolve(f, "key_numbers", tier_map)
            for f in brief.structured_facts.key_numbers
        ],
        key_entities=[
            _resolve(f, "key_entities", tier_map)
            for f in brief.structured_facts.key_entities
        ],
        surprising_claims=[
            _resolve(f, "surprising_claims", tier_map)
            for f in brief.structured_facts.surprising_claims
        ],
        controversies=list(brief.structured_facts.controversies),
    )

    quality = run_quality_gate(brief, cleaned_facts)

    _MAX_WARNING_LINES = 10
    for w in quality.warnings[:_MAX_WARNING_LINES]:
        logger.warning("⚠️ Phase A 品質警告 [%s]: %s", w.code, w.message)
    if len(quality.warnings) > _MAX_WARNING_LINES:
        logger.warning("⚠️ ... 他 %d 件", len(quality.warnings) - _MAX_WARNING_LINES)

    return CleanedResearch(
        theme=brief.theme,
        angle=brief.angle,
        research_mode=brief.research_mode,
        research_content=brief.research_content,
        queries=list(brief.queries),
        sources=list(brief.research_sources),
        facts=cleaned_facts,
        quality_report=quality,
    )


def _build_tier_map(brief: ResearchBrief) -> dict[int, DomainTier]:
    """research_sources を 1-based の {source_idx: tier} に展開する。"""
    return {i + 1: s.domain_tier for i, s in enumerate(brief.research_sources)}


def _resolve(
    fact: _AnyFact,
    category: FactCategory,
    tier_map: dict[int, DomainTier],
) -> ResolvedFact:
    tier: DomainTier = tier_map.get(fact.source_idx, "B")
    is_highly_specific = "highly_specific" in fact.flags
    return ResolvedFact(
        category=category,
        text=_format_text(fact, category),
        source_idx=fact.source_idx,
        primary_source_tier=tier,
        cross_validated_sources=list(fact.cross_validated_sources),
        confidence=fact.confidence,
        flags=list(fact.flags),
        needs_review=is_highly_specific and tier == "B",
        raw=fact.model_dump(),
    )


def _format_text(fact: _AnyFact, category: FactCategory) -> str:
    """Phase B のプロンプト整形向けの表示文字列。"""
    if category == "key_numbers":
        kn = fact  # type: KeyNumber
        return f"{kn.value}{kn.unit} — {kn.context}"
    if category == "key_entities":
        ke = fact  # type: KeyEntity
        return f"{ke.name} ({ke.type}) — {ke.role}"
    if category == "surprising_claims":
        sc = fact  # type: SurprisingClaim
        return f"{sc.statement} ({sc.why_surprising})"
    raise ValueError(f"unknown category: {category}")
