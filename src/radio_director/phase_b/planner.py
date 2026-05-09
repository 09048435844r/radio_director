"""Phase B のオーケストレーション: prompt -> LLM -> parse -> ShowSpec。

Step 1 SSOT 化: thumbnail_title (max_length=15) 違反等の Pydantic
ValidationError を 1 回吸収するため max_attempts=2 (初回 + 1 retry)
を導入。Phase B は高コスト (~110 秒/コール) なので過剰 retry は避ける。
"""

from __future__ import annotations

import logging
import time

from radio_director.models.cleaned_research import CleanedResearch
from radio_director.models.show_spec import ShowSpec
from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_b.parser import ShowSpecParseError, parse_show_spec
from radio_director.phase_b.prompt_builder import build_prompt

logger = logging.getLogger(__name__)


def plan_show(
    cleaned: CleanedResearch,
    *,
    client: LLMClient | None = None,
    temperature: float = 0.5,
    max_tokens: int = 4096,
    max_attempts: int = 2,
) -> ShowSpec:
    """CleanedResearch から ShowSpec を生成する。

    LLM 出力が ShowSpecParseError (Pydantic ValidationError 含む) で失敗した
    場合は最大 max_attempts 回まで retry する。最終的に失敗したら最後の
    例外を伝播する。

    実機検証 (§22.5) のため、prompt/output の文字数と所要時間を info ログに
    出力する。トークン数は日本語想定の単純係数 (chars/2) で概算ログのみ。
    """
    client = client or LLMClient.from_env()
    prompt = build_prompt(cleaned)

    last_exc: ShowSpecParseError | None = None
    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        raw = client.generate(
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        elapsed = time.monotonic() - started

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
            logger.warning(
                "⚠️ Phase B attempt %d/%d failed: %s",
                attempt,
                max_attempts,
                exc,
            )

    assert last_exc is not None
    raise last_exc
