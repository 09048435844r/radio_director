"""Phase B のオーケストレーション: prompt -> LLM -> parse -> ShowSpec。"""

from __future__ import annotations

import logging
import time

from radio_director.models.cleaned_research import CleanedResearch
from radio_director.models.show_spec import ShowSpec
from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_b.parser import parse_show_spec
from radio_director.phase_b.prompt_builder import build_prompt

logger = logging.getLogger(__name__)


def plan_show(
    cleaned: CleanedResearch,
    *,
    client: LLMClient | None = None,
    temperature: float = 0.5,
    max_tokens: int = 4096,
) -> ShowSpec:
    """CleanedResearch から ShowSpec を生成する。

    実機検証 (§22.5) のため、prompt/output の文字数と所要時間を info ログに
    出力する。トークン数は日本語想定の単純係数 (chars/2) で概算ログのみ。
    """
    client = client or LLMClient.from_env()
    prompt = build_prompt(cleaned)

    started = time.monotonic()
    raw = client.generate(
        prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=True,
    )
    elapsed = time.monotonic() - started

    logger.info(
        "Phase B summary: prompt_chars=%d output_chars=%d "
        "approx_prompt_tokens=%d approx_output_tokens=%d elapsed_sec=%.1f",
        len(prompt),
        len(raw),
        len(prompt) // 2,
        len(raw) // 2,
        elapsed,
    )

    return parse_show_spec(raw)
