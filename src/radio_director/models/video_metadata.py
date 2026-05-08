"""Phase D が生成する動画メタデータ。

title / description / hashtags は LLM 1 コールで生成。chapters は Script の
segment 構造から決定論的に算出（1 turn ≒ 5 秒）。thumbnail_title は
ShowSpec からの機械的コピー、references は Phase D の citation_normalizer
が解決した実引用 source_idx から構築（LLM コール追加禁止、Step 1 SSOT 化）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class Chapter(BaseModel):
    timestamp: str
    title: str


class SourceRef(BaseModel):
    """Phase D で確定した引用ソースの軽量参照（Step 1 SSOT 化）。"""

    url: HttpUrl
    title: str | None = None
    tier: Literal["AAA", "AA", "A", "B"] | None = None


class VideoMetadata(BaseModel):
    title: str
    thumbnail_title: str = Field(..., min_length=1, max_length=15)
    description: str = Field(min_length=50, max_length=2000)
    hashtags: list[str] = Field(min_length=3, max_length=15)
    chapters: list[Chapter] = Field(min_length=2)
    references: list[SourceRef] = Field(default_factory=list)
