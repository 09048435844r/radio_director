"""Phase C の出力スキーマ。番組台本の構造化表現。

intro / deep_dive×N / conclusion の各 segment を持ち、各 segment は
A=ずんだもん / B=四国めたん の対話ターンで構成される。
仕様 §13.3 を参照。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from radio_director.models.show_spec import ShowSpec

DialogSpeaker = Literal["A", "B"]
SegmentType = Literal["intro", "deep_dive", "conclusion"]


class DialogTurn(BaseModel):
    speaker: DialogSpeaker
    text: str


class ScriptSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    segment_type: SegmentType
    topic_index: int | None = None
    title: str
    turns: list[DialogTurn] = Field(min_length=4)


class SegmentMetrics(BaseModel):
    prompt_chars: int
    output_chars: int
    elapsed_sec: float
    attempts: int
    used_fallback: bool


class Script(BaseModel):
    show_spec: ShowSpec
    segments: list[ScriptSegment] = Field(min_length=4, max_length=6)
    metrics: dict[str, SegmentMetrics]
