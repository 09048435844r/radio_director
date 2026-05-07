"""research_pipeline が出力する research_brief.json (v1.6) の入力スキーマ。

interface_spec.md v1.6.0 §3.1 に準拠。v1.6 拡張フィールド
(confidence / cross_validated_sources / flags) は Optional + default で
v1.5 入力との後方互換を保つ。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

DomainTier = Literal["AAA", "AA", "A", "B"]
Confidence = Literal["high", "medium", "low"]


class ResearchSource(BaseModel):
    title: str
    url: str
    snippet: Optional[str] = None
    domain_score: int = 0
    domain_tier: DomainTier


class _FactBase(BaseModel):
    source_idx: int
    cross_validated_sources: list[int] = Field(default_factory=list)
    confidence: Confidence = "medium"
    flags: list[str] = Field(default_factory=list)


class KeyNumber(_FactBase):
    value: str
    unit: str
    context: str


class KeyEntity(_FactBase):
    name: str
    type: str
    role: str


class SurprisingClaim(_FactBase):
    statement: str
    why_surprising: str


class Controversy(BaseModel):
    position_a: str
    position_b: str
    source_indices: list[int]


class StructuredFacts(BaseModel):
    key_numbers: list[KeyNumber] = Field(default_factory=list)
    key_entities: list[KeyEntity] = Field(default_factory=list)
    surprising_claims: list[SurprisingClaim] = Field(default_factory=list)
    controversies: list[Controversy] = Field(default_factory=list)


class ResearchBrief(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str
    theme: str
    angle: str
    research_mode: str
    created_at: str
    research_content: str
    research_sources: list[ResearchSource]
    queries: list[str]
    structured_facts: StructuredFacts
