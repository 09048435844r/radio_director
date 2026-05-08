"""Phase D の出力スキーマ。Script + 検証メトリクス + warnings + VideoMetadata。

ハルシネーション検出と出典タグ整合性検証は決定論で行い、警告のみを発する
（修正は v1 ではしない）。研究側 §3.1.1 の highly_specific 判定をそのまま
台本中の数値にも適用し、structured_facts と突き合わせて false-positive
候補を抽出する。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from radio_director.models.script import Script
from radio_director.models.video_metadata import SourceRef, VideoMetadata

__all__ = [
    "WarningCode",
    "VerificationWarning",
    "VerifiedScriptMetrics",
    "VerifiedScript",
    "SourceRef",
]

WarningCode = Literal[
    "unmatched_number",
    "highly_specific_unmatched",
    "tier_mismatch",
    "unknown_source_idx",
    "low_match_ratio",
    "needs_review_used",
]


class VerificationWarning(BaseModel):
    code: WarningCode
    message: str
    location: str


class VerifiedScriptMetrics(BaseModel):
    total_numbers_extracted: int
    matched_to_structured_facts: int
    matched_ratio: float
    highly_specific_count: int
    highly_specific_unmatched: int
    false_positive_candidates: int
    citation_tags_total: int
    citation_tags_normalized: int
    citation_tags_inconsistent: int


class VerifiedScript(BaseModel):
    script: Script
    metrics: VerifiedScriptMetrics
    warnings: list[VerificationWarning]
    metadata: VideoMetadata
