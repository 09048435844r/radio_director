"""実機 LLM (Mac Studio Proxy → GX10 vLLM Qwen3.5-122B) との統合テスト。

CI ではスキップ。手動検証は次で実行:
    RADIO_DIRECTOR_INTEGRATION=1 pytest tests/phase_b/test_integration_llm.py -v -s

仕様 §22.5 の検証項目を測定:
- prompt 文字数 / 出力文字数 / 概算トークン数
- レスポンス時間
- ShowSpec の構造 (topics 数、key_claims 件数、angle 一致)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pytest

from radio_director.models.research_brief import ResearchBrief
from radio_director.phase_a.decoder import decode
from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_b.planner import plan_show
from radio_director.phase_b.prompt_builder import build_prompt

SAMPLE_PATH = Path(__file__).parent.parent / "data" / "research_brief_sample.json"

pytestmark = pytest.mark.skipif(
    not os.environ.get("RADIO_DIRECTOR_INTEGRATION"),
    reason="LLM 統合テスト (RADIO_DIRECTOR_INTEGRATION=1 で有効化)",
)


@pytest.fixture(scope="module")
def cleaned():
    payload = SAMPLE_PATH.read_text(encoding="utf-8")
    return decode(ResearchBrief.model_validate_json(payload))


@pytest.fixture(scope="module")
def llm_client():
    return LLMClient.from_env()


def test_end_to_end_show_generation(cleaned, llm_client, caplog):
    caplog.set_level(logging.INFO)

    prompt = build_prompt(cleaned)
    print(f"\n[§22.5] prompt_chars        = {len(prompt):,}")
    print(f"[§22.5] approx_prompt_tokens = {len(prompt) // 2:,}")

    started = time.monotonic()
    show = plan_show(cleaned, client=llm_client)
    elapsed = time.monotonic() - started

    print(f"[§22.5] elapsed_sec          = {elapsed:.1f}")
    print(f"[§22.5] topics_count         = {len(show.topics)}")
    total_claims = sum(len(t.key_claims) for t in show.topics)
    print(f"[§22.5] total_claims         = {total_claims}")
    print(f"[§22.5] title                = {show.title!r}")

    assert 2 <= len(show.topics) <= 4
    assert show.angle == cleaned.angle, "angle が再解釈・改変されている"
    for i, topic in enumerate(show.topics):
        assert len(topic.key_claims) >= 1, f"topic[{i}] に key_claims がない"
