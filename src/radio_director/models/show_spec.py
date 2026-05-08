"""Phase B の出力スキーマ。番組企画書の構造化表現。

LLM (Qwen3.5-122B) が「ラジオ番組ディレクターとして」生成する企画書を
ShowSpec として受け取る。各 Claim は元 structured_facts から source_idx /
tier / confidence を継承し、Phase D の検証で trace に使う。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from radio_director.models.research_brief import Confidence, DomainTier


class Claim(BaseModel):
    text: str
    source_idx: int
    source_tier: DomainTier
    confidence: Confidence


class TopicSpec(BaseModel):
    title: str
    hook: str
    key_claims: list[Claim] = Field(min_length=1)
    tone: str
    estimated_turns: int = Field(ge=1, le=30)


class ShowSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    hook: str
    angle: str
    arc: str
    tone: str
    topics: list[TopicSpec] = Field(min_length=2, max_length=4)
    conclusion_message: str
