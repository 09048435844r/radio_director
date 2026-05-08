"""Phase D のオーケストレーション。

verify(script, cleaned_research) -> VerifiedScript
  1. extract_numbers (決定論)
  2. detect_hallucinations + check_needs_review_usage (決定論)
  3. normalize_citations (決定論)
  4. generate_metadata (LLM 1 コール)
  5. メトリクス集計 + warnings 集約 -> VerifiedScript
"""

from __future__ import annotations

import logging

from radio_director.models.cleaned_research import CleanedResearch
from radio_director.models.script import Script
from radio_director.models.verified_script import (
    VerificationWarning,
    VerifiedScript,
    VerifiedScriptMetrics,
)
from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_d.citation_normalizer import normalize_citations
from radio_director.phase_d.hallucination_detector import (
    build_fact_index,
    check_needs_review_usage,
    detect_hallucinations,
)
from radio_director.phase_d.metadata_generator import generate_metadata
from radio_director.phase_d.number_extractor import extract_numbers

logger = logging.getLogger(__name__)


def verify(
    script: Script,
    cleaned_research: CleanedResearch,
    *,
    client: LLMClient | None = None,
) -> VerifiedScript:
    numbers = extract_numbers(script)
    fact_index = build_fact_index(cleaned_research)
    halluc_stats, halluc_warnings = detect_hallucinations(numbers, fact_index)
    needs_review_warnings = check_needs_review_usage(script, cleaned_research)

    citation_findings, citation_warnings = normalize_citations(script, cleaned_research)

    metadata = generate_metadata(script, client=client)

    metrics = VerifiedScriptMetrics(
        total_numbers_extracted=halluc_stats.total,
        matched_to_structured_facts=halluc_stats.matched,
        matched_ratio=halluc_stats.matched_ratio,
        highly_specific_count=halluc_stats.highly_specific_count,
        highly_specific_unmatched=halluc_stats.highly_specific_unmatched,
        false_positive_candidates=halluc_stats.highly_specific_unmatched,
        citation_tags_total=len(citation_findings),
        citation_tags_normalized=sum(
            1 for c in citation_findings if c.canonical != c.raw
        ),
        citation_tags_inconsistent=sum(
            1 for c in citation_findings if not c.is_consistent
        ),
    )
    warnings: list[VerificationWarning] = (
        halluc_warnings + needs_review_warnings + citation_warnings
    )

    logger.info(
        "Phase D verify done: numbers=%d matched=%d (ratio=%.2f) "
        "highly_specific=%d (unmatched=%d) citations=%d (inconsistent=%d) warnings=%d",
        metrics.total_numbers_extracted,
        metrics.matched_to_structured_facts,
        metrics.matched_ratio,
        metrics.highly_specific_count,
        metrics.highly_specific_unmatched,
        metrics.citation_tags_total,
        metrics.citation_tags_inconsistent,
        len(warnings),
    )

    return VerifiedScript(
        script=script,
        metrics=metrics,
        warnings=warnings,
        metadata=metadata,
    )
