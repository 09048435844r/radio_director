"""Phase B のオーケストレーション: prompt -> LLM -> parse -> ShowSpec。

Step 1 SSOT 化: thumbnail_title (max_length=15) 違反等の Pydantic
ValidationError を 1 回吸収するため max_attempts=2 (初回 + 1 retry)
を導入。

Step 9 partial (postscript): DGX/exo で thumbnail_title 15字制約が
確率的失敗する事象 (backlog §14.1) への対応で 3 層構造に拡張:
  1. max_attempts を 3 に増加 (config 外出し)
  2. retry 時に失敗理由を prompt に inline 表示
  3. 最終 LLM 失敗時に deterministic な末尾切り詰め fallback
"""

from __future__ import annotations

import logging
import time

from pydantic import ValidationError

from radio_director import config as _config
from radio_director.models.cleaned_research import CleanedResearch
from radio_director.models.show_spec import ShowSpec
from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_b.parser import (
    ShowSpecParseError,
    parse_show_spec,
    parse_show_spec_dict,
)
from radio_director.phase_b.prompt_builder import build_prompt

logger = logging.getLogger(__name__)


def plan_show(
    cleaned: CleanedResearch,
    *,
    client: LLMClient | None = None,
    temperature: float = 0.5,
    max_tokens: int = 4096,
    max_attempts: int | None = None,
) -> ShowSpec:
    """CleanedResearch から ShowSpec を生成する。

    LLM 出力が ShowSpecParseError (Pydantic ValidationError 含む) で失敗した
    場合は最大 max_attempts 回まで retry する。max_attempts 省略時は config の
    PHASE_B_PLANNER_MAX_ATTEMPTS を採用 (デフォルト 3)。
    最終的に失敗しても thumbnail_title の長さ違反だけが原因ならば
    deterministic な末尾切り詰め fallback で完走させる。

    実機検証 (§22.5) のため、prompt/output の文字数と所要時間を info ログに
    出力する。
    """
    client = client or LLMClient.from_env()
    base_prompt = build_prompt(cleaned)
    if max_attempts is None:
        max_attempts = int(_config.PHASE_B_PLANNER_MAX_ATTEMPTS or 2)

    last_exc: ShowSpecParseError | None = None
    last_raw: str | None = None
    last_failure_reason: str | None = None
    for attempt in range(1, max_attempts + 1):
        # retry 時に失敗理由を prompt に inline (Step 9 partial)
        prompt = base_prompt
        if (
            attempt > 1
            and _config.PHASE_B_RETRY_INCLUDE_FAILURE_REASON
            and last_failure_reason
        ):
            prompt = (
                f"# 前回の試行 ({attempt - 1}/{max_attempts}) で失敗した理由\n"
                f"{last_failure_reason}\n\n"
                "上記の問題を必ず修正してください。"
                f"特に thumbnail_title は {_config.PHASE_B_THUMBNAIL_TITLE_MAX_LENGTH}字以内にしてください。\n\n"
                + base_prompt
            )

        started = time.monotonic()
        raw = client.generate(
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        elapsed = time.monotonic() - started
        last_raw = raw

        logger.info(
            "📝 Phase B attempt %d/%d: prompt_chars=%d output_chars=%d "
            "approx_prompt_tokens=%d approx_output_tokens=%d elapsed=%.1fs",
            attempt,
            max_attempts,
            len(prompt),
            len(raw),
            len(prompt) // 2,
            len(raw) // 2,
            elapsed,
        )

        try:
            return parse_show_spec(raw)
        except ShowSpecParseError as exc:
            last_exc = exc
            last_failure_reason = _build_failure_reason(exc, raw)
            logger.warning(
                "⚠️ Phase B attempt %d/%d failed: %s",
                attempt,
                max_attempts,
                exc,
            )

    # 最終フォールバック: thumbnail_title 長さ違反のみが原因なら deterministic 修正
    if (
        _config.PHASE_B_THUMBNAIL_TITLE_TRUNCATE_ENABLED
        and last_raw is not None
        and _is_thumbnail_too_long_error(last_exc)
    ):
        try:
            obj = parse_show_spec_dict(last_raw)
            tt = obj.get("thumbnail_title")
            max_len = int(_config.PHASE_B_THUMBNAIL_TITLE_MAX_LENGTH or 15)
            if isinstance(tt, str) and len(tt) > max_len:
                truncated = tt[:max_len]
                obj["thumbnail_title"] = truncated
                spec = ShowSpec.model_validate(obj)
                logger.warning(
                    "⚠️ Phase B thumbnail_title fallback truncate: %r (%d字) → %r (%d字)",
                    tt,
                    len(tt),
                    truncated,
                    len(truncated),
                )
                return spec
        except (ShowSpecParseError, ValidationError) as fallback_exc:
            logger.warning(
                "⚠️ Phase B thumbnail_title fallback も失敗: %s",
                fallback_exc,
            )

    assert last_exc is not None
    raise last_exc


def _build_failure_reason(exc: ShowSpecParseError, raw: str) -> str:
    """Pydantic / parse 失敗の理由を retry prompt 用に簡潔な日本語で説明する。"""
    msg = str(exc)
    parts = [f"発生したエラー: {msg[:240]}"]
    # thumbnail_title が長すぎた場合は具体的な文字を含める (LLM への hint)
    try:
        obj = parse_show_spec_dict(raw)
        tt = obj.get("thumbnail_title")
        max_len = int(_config.PHASE_B_THUMBNAIL_TITLE_MAX_LENGTH or 15)
        if isinstance(tt, str) and len(tt) > max_len:
            parts.append(
                f"thumbnail_title が「{tt}」({len(tt)}字) で {max_len}字を超えています。"
            )
    except (ShowSpecParseError, Exception):  # noqa: BLE001
        pass
    return " / ".join(parts)


def _is_thumbnail_too_long_error(exc: ShowSpecParseError | None) -> bool:
    """ShowSpecParseError が thumbnail_title の長さ違反のみに起因するかを判定する。"""
    if exc is None:
        return False
    msg = str(exc)
    return "thumbnail_title" in msg and (
        "at most" in msg or "string_too_long" in msg or "max_length" in msg
    )
