"""数値ベースのハルシネーション検出（決定論）。

CleanedResearch.facts.key_numbers から canonical 形のインデックスを構築し、
台本から抽出した数値と突き合わせる。highly_specific フラグが立った数値が
インデックスに無ければ false-positive 候補として警告する（仕様 §10.3）。
v1 は警告のみで自動修正は行わない（FactFix は v2 以降）。
"""

from __future__ import annotations

from dataclasses import dataclass

from radio_director.models.cleaned_research import CleanedResearch, ResolvedFact
from radio_director.models.script import Script
from radio_director.models.verified_script import VerificationWarning
from radio_director.phase_d.number_extractor import ExtractedNumber

LOW_MATCH_RATIO_THRESHOLD = 0.5


@dataclass(frozen=True)
class HallucinationStats:
    total: int
    matched: int
    unmatched: int
    matched_ratio: float
    highly_specific_count: int
    highly_specific_unmatched: int


def build_fact_index(cleaned_research: CleanedResearch) -> dict[str, ResolvedFact]:
    """canonical 形 (value+unit、コンマ除去) -> ResolvedFact のマッピング。"""
    index: dict[str, ResolvedFact] = {}
    for fact in cleaned_research.facts.key_numbers:
        canon = _canonicalize(fact.raw.get("value", ""), fact.raw.get("unit", ""))
        if canon:
            index.setdefault(canon, fact)
    return index


def detect_hallucinations(
    extracted: list[ExtractedNumber],
    fact_index: dict[str, ResolvedFact],
) -> tuple[HallucinationStats, list[VerificationWarning]]:
    matched = 0
    unmatched = 0
    highly_specific_count = 0
    highly_specific_unmatched = 0
    warnings: list[VerificationWarning] = []

    for num in extracted:
        in_facts = num.canonical in fact_index
        if in_facts:
            matched += 1
        else:
            unmatched += 1
            warnings.append(
                VerificationWarning(
                    code="unmatched_number",
                    message=f"{num.raw!r} が structured_facts に見当たりません",
                    location=num.segment_id,
                )
            )
        if num.is_highly_specific:
            highly_specific_count += 1
            if not in_facts:
                highly_specific_unmatched += 1
                warnings.append(
                    VerificationWarning(
                        code="highly_specific_unmatched",
                        message=(
                            f"{num.raw!r} は highly_specific かつ structured_facts に未登録 "
                            "(false-positive 候補)"
                        ),
                        location=num.segment_id,
                    )
                )

    total = matched + unmatched
    matched_ratio = matched / total if total else 1.0

    if total > 0 and matched_ratio < LOW_MATCH_RATIO_THRESHOLD:
        warnings.append(
            VerificationWarning(
                code="low_match_ratio",
                message=(
                    f"matched_ratio {matched_ratio:.1%} "
                    f"(推奨 {LOW_MATCH_RATIO_THRESHOLD:.0%} 以上)"
                ),
                location="overall",
            )
        )

    stats = HallucinationStats(
        total=total,
        matched=matched,
        unmatched=unmatched,
        matched_ratio=matched_ratio,
        highly_specific_count=highly_specific_count,
        highly_specific_unmatched=highly_specific_unmatched,
    )
    return stats, warnings


def check_needs_review_usage(
    script: Script, cleaned_research: CleanedResearch
) -> list[VerificationWarning]:
    """needs_review=True の fact text が台本本文に出現しているかを確認し警告を返す。"""
    needs_review_texts: list[tuple[ResolvedFact, str]] = []
    for fact in cleaned_research.facts.key_numbers:
        if fact.needs_review:
            value = fact.raw.get("value", "")
            unit = fact.raw.get("unit", "")
            needs_review_texts.append((fact, f"{value}{unit}".strip()))

    if not needs_review_texts:
        return []

    warnings: list[VerificationWarning] = []
    for seg in script.segments:
        seg_id = (
            f"deep_dive_{seg.topic_index}"
            if seg.segment_type == "deep_dive"
            else seg.segment_type
        )
        body = " ".join(t.text for t in seg.turns)
        for fact, key in needs_review_texts:
            if key and key in body:
                warnings.append(
                    VerificationWarning(
                        code="needs_review_used",
                        message=(
                            f"needs_review な fact ({key}, src={fact.source_idx}) "
                            "が台本に引用されています。手動確認推奨。"
                        ),
                        location=seg_id,
                    )
                )
    return warnings


def _canonicalize(value: str, unit: str) -> str:
    if not value:
        return ""
    return value.replace(",", "").strip() + (unit or "").strip()
