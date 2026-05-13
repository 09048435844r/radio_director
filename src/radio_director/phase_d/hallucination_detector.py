"""数値ベースのハルシネーション検出（決定論）。

CleanedResearch.facts.key_numbers から canonical 形のインデックスを構築し、
台本から抽出した数値と突き合わせる。highly_specific フラグが立った数値が
インデックスに無ければ false-positive 候補として警告する（仕様 §10.3）。
v1 は警告のみで自動修正は行わない（FactFix は v2 以降）。

P1 (Step 8 v2): "1000 億" (script) vs "1000億パラメータ" (structured_facts)
のような スペース・単位の違いだけで unmatched 判定される事象を 2026-05-13
exo 本運用で観測。canonical 化に全角→半角・スペース除去・日本語単位剥がしを
追加する。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from radio_director import config as _config
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
    """canonical 形 (value+unit、コンマ除去) -> ResolvedFact のマッピング。

    P1: 正規化を強化し、同一 fact が複数表記でマッチするよう登録キーも増やす。
    """
    index: dict[str, ResolvedFact] = {}
    for fact in cleaned_research.facts.key_numbers:
        value = fact.raw.get("value", "")
        unit = fact.raw.get("unit", "")
        # 旧 canonical (後方互換)
        canon = _canonicalize(value, unit)
        if canon:
            index.setdefault(canon, fact)
        # P1: 正規化 canonical (script 側もこれで突合される)
        if _config.PHASE_D_NUMBER_NORMALIZATION_ENABLED:
            normalized = _normalize_canonical(canon)
            if normalized and normalized != canon:
                index.setdefault(normalized, fact)
            # value のみの正規化キー (script で単位なし数値と整合させるため)
            value_only = _normalize_canonical(_canonicalize(value, ""))
            if value_only and value_only != canon and value_only != normalized:
                index.setdefault(value_only, fact)
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
        # P1: 旧 canonical で先に判定 (後方互換)。マッチしなければ
        # normalize_canonical を試み、両者で fact_index に存在するか確認する。
        in_facts = num.canonical in fact_index
        if not in_facts and _config.PHASE_D_NUMBER_NORMALIZATION_ENABLED:
            normalized = _normalize_canonical(num.canonical)
            if normalized and normalized in fact_index:
                in_facts = True
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


def _normalize_canonical(canon: str) -> str:
    """P1 (Step 8 v2): canonical 文字列をさらに正規化する。

    - 全角→半角 (Unicode NFKC)
    - 全空白 (半角・全角) を除去
    - カンマ・読点除去
    - 日本語単位の剥がし (パラメータ/件/名/個/台/本/年/月/日/円/時間/分/秒/ドル/ユーロ 等)
    - 単位 % / 倍 / mm / kg などは保持 (それ自体が数値の意味を変える)
    """
    if not canon:
        return ""
    s = unicodedata.normalize("NFKC", canon)
    # スペース除去 (半角/全角/U+3000)
    s = s.replace(" ", "").replace("　", "").replace("\t", "")
    # カンマ除去 (NFKC で全角カンマも半角になるはず)
    s = s.replace(",", "")
    # 日本語単位の剥がし: 末尾から該当語をすべて削る
    strip_units = tuple(_config.PHASE_D_NUMBER_STRIP_UNITS or ())
    changed = True
    while changed:
        changed = False
        for unit in strip_units:
            if unit and s.endswith(unit):
                s = s[: -len(unit)]
                changed = True
                break
    return s.strip()
