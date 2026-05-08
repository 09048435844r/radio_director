"""VideoMetadata 生成。LLM 1 コール (title/description/hashtags) +
決定論的 chapters (1 turn ≒ 5 秒)。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from radio_director.models.script import Script
from radio_director.models.show_spec import ShowSpec
from radio_director.models.video_metadata import Chapter, VideoMetadata
from radio_director.phase_b.llm_client import LLMClient

logger = logging.getLogger(__name__)

SECONDS_PER_TURN = 5

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*|```", flags=re.MULTILINE)


class MetadataGenerationError(Exception):
    """メタデータ生成 (LLM コール / パース / バリデーション) が失敗した場合。"""


def generate_metadata(
    script: Script,
    *,
    client: LLMClient | None = None,
    temperature: float = 0.5,
    max_tokens: int = 2048,
) -> VideoMetadata:
    client = client or LLMClient.from_env()
    prompt = _build_prompt(script.show_spec)

    raw = client.generate(
        prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=True,
    )
    parsed = _parse_metadata_response(raw)

    chapters = build_chapters(script)

    try:
        return VideoMetadata(
            title=parsed["title"],
            description=parsed["description"],
            hashtags=_clean_hashtags(parsed["hashtags"]),
            chapters=chapters,
        )
    except ValidationError as exc:
        raise MetadataGenerationError(
            f"VideoMetadata validation failed: {exc}"
        ) from exc


def build_chapters(script: Script) -> list[Chapter]:
    """segment 構造から chapters を決定論的に算出する。"""
    chapters: list[Chapter] = []
    cumulative_turns = 0
    for seg in script.segments:
        timestamp = _format_timestamp(cumulative_turns * SECONDS_PER_TURN)
        title = _resolve_chapter_title(seg, script.show_spec)
        chapters.append(Chapter(timestamp=timestamp, title=title))
        cumulative_turns += len(seg.turns)
    return chapters


def _resolve_chapter_title(seg, show_spec: ShowSpec) -> str:
    if seg.segment_type == "intro":
        return "イントロ"
    if seg.segment_type == "deep_dive":
        idx = seg.topic_index or 0
        return show_spec.topics[idx].title
    return "まとめ"


def _format_timestamp(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _build_prompt(show_spec: ShowSpec) -> str:
    topics_list = "\n".join(
        f"  {i + 1}. {t.title}" for i, t in enumerate(show_spec.topics)
    )
    return f"""あなたは YouTube ラジオ番組のメタデータ最適化担当です。
以下の番組仕様から、視聴者が見つけやすく・クリックしたくなる
title / description / hashtags を生成してください。

# 番組仕様
title (案): {show_spec.title}
angle: {show_spec.angle}
hook: {show_spec.hook}
arc: {show_spec.arc}
扱うトピック:
{topics_list}
conclusion_message: {show_spec.conclusion_message}

# 出力ルール
- title: 60 字以内、検索でクリックされやすい表現
- description: 200-500 字、概要 + 各トピックの一行紹介
- hashtags: 5-10 個、日本語/英語混在可、頭の # は付けない

# 出力フォーマット (JSON、以下のスキーマに厳密に従うこと)
{{
  "title": "...",
  "description": "...",
  "hashtags": ["タグ1", "タグ2"]
}}
"""


def _parse_metadata_response(raw: str) -> dict[str, Any]:
    cleaned = _CODE_FENCE_RE.sub("", _THINK_TAG_RE.sub("", raw)).strip()
    obj = _try_load_json(cleaned)
    if obj is None:
        extracted = _extract_first_json_object(cleaned)
        if extracted is None:
            raise MetadataGenerationError(
                f"JSON が見つかりません (head={cleaned[:200]!r})"
            )
        obj = _try_load_json(extracted)
        if obj is None:
            raise MetadataGenerationError(
                f"JSON のパースに失敗 (head={extracted[:200]!r})"
            )
    if not isinstance(obj, dict):
        raise MetadataGenerationError("トップレベルが JSON オブジェクトではありません")
    for key in ("title", "description", "hashtags"):
        if key not in obj:
            raise MetadataGenerationError(f"必須キー {key!r} が欠落しています")
    if not isinstance(obj["hashtags"], list):
        raise MetadataGenerationError("hashtags は配列である必要があります")
    return obj


def _try_load_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _clean_hashtags(raw: list[Any]) -> list[str]:
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        tag = item.strip().lstrip("#").strip()
        if tag:
            cleaned.append(tag)
    return cleaned
