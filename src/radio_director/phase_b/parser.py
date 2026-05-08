"""LLM 出力 (テキスト) を ShowSpec に変換する。

vLLM の guided decoding (format='json') が有効なら通常 1 回で正しい JSON を
返すが、念のため <think>...</think> やコードフェンスを除去するフォールバック
を持つ。v1 ではリトライしない（失敗時は例外を呼び出し側に伝播）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from radio_director.models.show_spec import ShowSpec

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*|```", flags=re.MULTILINE)


class ShowSpecParseError(Exception):
    """LLM 出力を ShowSpec に変換できなかった場合に投げる。"""


def parse_show_spec(raw: str) -> ShowSpec:
    cleaned = _strip_code_fences(_strip_think_tags(raw)).strip()

    obj = _try_load_json(cleaned)
    if obj is None:
        extracted = _extract_first_json_object(cleaned)
        if extracted is None:
            raise ShowSpecParseError(
                f"JSON オブジェクトが見つかりません (head={cleaned[:200]!r})"
            )
        obj = _try_load_json(extracted)
        if obj is None:
            raise ShowSpecParseError(
                f"JSON のパースに失敗しました (head={extracted[:200]!r})"
            )

    if not isinstance(obj, dict):
        raise ShowSpecParseError(
            f"トップレベルが JSON オブジェクトではありません (type={type(obj).__name__})"
        )

    try:
        return ShowSpec.model_validate(obj)
    except ValidationError as exc:
        raise ShowSpecParseError(f"ShowSpec validation failed: {exc}") from exc


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
