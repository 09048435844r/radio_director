"""LLM 出力 (turns 配列を含む JSON) を ScriptSegment に変換する。

Phase B の parser パターンと同じく <think> タグ・コードフェンス除去 →
JSON 抽出 → Pydantic validate の流れ。LLM が返すのは {"turns": [...]} のみ
で、segment_type / topic_index / title はこの関数の引数で組み立てる。
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from radio_director.models.script import ScriptSegment, SegmentType

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*|```", flags=re.MULTILINE)


class ScriptParseError(Exception):
    """LLM 出力を ScriptSegment に変換できなかった場合に投げる。"""


def parse_segment(
    raw: str,
    *,
    segment_type: SegmentType,
    topic_index: int | None,
    title: str,
) -> ScriptSegment:
    cleaned = _strip_code_fences(_strip_think_tags(raw)).strip()

    obj = _try_load_json(cleaned)
    if obj is None:
        extracted = _extract_first_json_object(cleaned)
        if extracted is None:
            raise ScriptParseError(
                f"JSON オブジェクトが見つかりません (head={cleaned[:200]!r})"
            )
        obj = _try_load_json(extracted)
        if obj is None:
            raise ScriptParseError(
                f"JSON のパースに失敗しました (head={extracted[:200]!r})"
            )

    if not isinstance(obj, dict):
        raise ScriptParseError(
            f"トップレベルが JSON オブジェクトではありません (type={type(obj).__name__})"
        )
    if "turns" not in obj:
        raise ScriptParseError(f"`turns` キーがありません (keys={list(obj.keys())})")

    try:
        return ScriptSegment(
            segment_type=segment_type,
            topic_index=topic_index,
            title=title,
            turns=obj["turns"],
        )
    except ValidationError as exc:
        raise ScriptParseError(f"ScriptSegment validation failed: {exc}") from exc


def _strip_think_tags(text: str) -> str:
    return _THINK_TAG_RE.sub("", text)


def _strip_code_fences(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text)


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
