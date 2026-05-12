"""出典タグの正規化と整合性検証（決定論）。

Phase B/C の台本には [AAA] / [16] / [16][AAA] / [src=16][AAA][medium] と
複数形式が混在しうる。正規化ルールは「tier のみ [AAA] が canonical」。
src がある場合は finding データとして保持するが本文表記は簡潔形に揃える。

整合性チェック:
  - tier_mismatch: src=N の domain_tier と tag の tier が一致しない
  - unknown_source_idx: src=N が research_sources の範囲外
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from radio_director.models.cleaned_research import CleanedResearch
from radio_director.models.research_brief import DomainTier
from radio_director.models.script import Script
from radio_director.models.verified_script import VerificationWarning

_TIER_TOKEN = r"AAA|AA|A|B"

_FULL_TAG_RE = re.compile(
    rf"\[src\s*=\s*(?P<src>\d+)\]\[(?P<tier>{_TIER_TOKEN})\](?:\[(?:high|medium|low)\])?"
)
_SRC_THEN_TIER_RE = re.compile(
    rf"\[(?P<src>\d+)\]\[(?P<tier>{_TIER_TOKEN})\]"
)
# C6 (Step 7): Phase C プロンプトを inline [src=N] のみに簡素化したため、
# [src=N] 単独形式も認識する。tier は cleaned_research.sources から逆引きする。
_SRC_ONLY_RE = re.compile(r"\[src\s*=\s*(?P<src>\d+)\]")
_TIER_ONLY_RE = re.compile(rf"\[(?P<tier>{_TIER_TOKEN})\]")


@dataclass(frozen=True)
class CitationFinding:
    raw: str
    canonical: str
    source_idx: int | None
    tier: DomainTier
    is_consistent: bool
    location: str


def normalize_citations(
    script: Script, cleaned_research: CleanedResearch
) -> tuple[list[CitationFinding], list[VerificationWarning]]:
    sources = cleaned_research.sources
    findings: list[CitationFinding] = []
    warnings: list[VerificationWarning] = []

    for seg in script.segments:
        seg_id = (
            f"deep_dive_{seg.topic_index}"
            if seg.segment_type == "deep_dive"
            else seg.segment_type
        )
        for turn in seg.turns:
            findings.extend(_scan_text(turn.text, seg_id, sources, warnings))

    return findings, warnings


def _scan_text(text, segment_id, sources, warnings):
    found: list[CitationFinding] = []
    consumed_spans: list[tuple[int, int]] = []

    for pattern in (_FULL_TAG_RE, _SRC_THEN_TIER_RE):
        for m in pattern.finditer(text):
            span = m.span()
            consumed_spans.append(span)
            src = int(m.group("src"))
            tier: DomainTier = m.group("tier")  # type: ignore[assignment]
            canonical = f"[src={src}][{tier}]"
            consistent, warn = _check_source(src, tier, sources, segment_id)
            if warn is not None:
                warnings.append(warn)
            found.append(
                CitationFinding(
                    raw=m.group(0),
                    canonical=canonical,
                    source_idx=src,
                    tier=tier,
                    is_consistent=consistent,
                    location=segment_id,
                )
            )

    # C6 (Step 7): [src=N] 単独形式 (新 Phase C inline 形式)
    for m in _SRC_ONLY_RE.finditer(text):
        span = m.span()
        if any(s <= span[0] < e for s, e in consumed_spans):
            continue  # 既に [src=N][TIER] として消費済み
        consumed_spans.append(span)
        src = int(m.group("src"))
        # tier は sources から逆引き
        if 1 <= src <= len(sources):
            tier: DomainTier = sources[src - 1].domain_tier  # type: ignore[assignment]
            consistent = True
        else:
            # 範囲外 src: warning を出す
            warnings.append(
                __import__(
                    "radio_director.models.verified_script", fromlist=["VerificationWarning"]
                ).VerificationWarning(
                    code="unknown_source_idx",
                    message=(
                        f"出典タグの src={src} が research_sources の範囲外 (1..{len(sources)})"
                    ),
                    location=segment_id,
                )
            )
            tier = "B"  # fallback
            consistent = False
        canonical = f"[src={src}][{tier}]"
        found.append(
            CitationFinding(
                raw=m.group(0),
                canonical=canonical,
                source_idx=src,
                tier=tier,
                is_consistent=consistent,
                location=segment_id,
            )
        )

    for m in _TIER_ONLY_RE.finditer(text):
        span = m.span()
        if any(s <= span[0] < e for s, e in consumed_spans):
            continue
        tier: DomainTier = m.group("tier")  # type: ignore[assignment]
        found.append(
            CitationFinding(
                raw=m.group(0),
                canonical=f"[{tier}]",
                source_idx=None,
                tier=tier,
                is_consistent=True,
                location=segment_id,
            )
        )

    return found


def _check_source(
    src: int, tier: DomainTier, sources, segment_id: str
) -> tuple[bool, VerificationWarning | None]:
    if src < 1 or src > len(sources):
        return False, VerificationWarning(
            code="unknown_source_idx",
            message=f"出典タグの src={src} が research_sources の範囲外 (1..{len(sources)})",
            location=segment_id,
        )
    expected = sources[src - 1].domain_tier
    if expected != tier:
        return False, VerificationWarning(
            code="tier_mismatch",
            message=(
                f"出典タグ src={src} の tier={tier!r} が "
                f"research_sources の {expected!r} と一致しません"
            ),
            location=segment_id,
        )
    return True, None
