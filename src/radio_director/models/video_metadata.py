"""Phase D が生成する動画メタデータ。

title / description / hashtags は LLM 1 コールで生成。chapters は Script の
segment 構造から決定論的に算出（1 turn ≒ 5 秒）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Chapter(BaseModel):
    timestamp: str
    title: str


class VideoMetadata(BaseModel):
    title: str
    description: str = Field(min_length=50, max_length=2000)
    hashtags: list[str] = Field(min_length=3, max_length=15)
    chapters: list[Chapter] = Field(min_length=2)
