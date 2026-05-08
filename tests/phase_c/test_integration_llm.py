"""Phase C 並列対話生成の実機 LLM 統合テスト。

CI ではスキップ。手動検証は次で実行:
    RADIO_DIRECTOR_INTEGRATION=1 pytest tests/phase_c/test_integration_llm.py -v -s

入力 fixture: tests/data/show_spec_sample.json (Phase B 実機実行で生成済)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pytest

from radio_director.models.show_spec import ShowSpec
from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_c.conductor import conduct

SHOW_SPEC_PATH = Path(__file__).parent.parent / "data" / "show_spec_sample.json"

pytestmark = pytest.mark.skipif(
    not os.environ.get("RADIO_DIRECTOR_INTEGRATION"),
    reason="LLM 統合テスト (RADIO_DIRECTOR_INTEGRATION=1 で有効化)",
)


@pytest.fixture(scope="module")
def show_spec() -> ShowSpec:
    return ShowSpec.model_validate_json(SHOW_SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def llm_client() -> LLMClient:
    return LLMClient.from_env()


def test_phase_c_end_to_end(show_spec, llm_client, caplog):
    caplog.set_level(logging.INFO)

    started = time.monotonic()
    script = conduct(show_spec, client=llm_client)
    total_elapsed = time.monotonic() - started

    print(f"\n[§24] total_elapsed_sec = {total_elapsed:.1f}")
    print(f"[§24] segments_count    = {len(script.segments)}")
    print(f"[§24] total_turns       = {sum(len(s.turns) for s in script.segments)}")
    print("[§24] per-segment metrics:")
    for key, m in script.metrics.items():
        print(
            f"  {key:14s} elapsed={m.elapsed_sec:5.1f}s "
            f"prompt_chars={m.prompt_chars:5d} output_chars={m.output_chars:5d} "
            f"attempts={m.attempts} fallback={m.used_fallback}"
        )

    expected_segments = 1 + len(show_spec.topics) + 1
    assert len(script.segments) == expected_segments

    assert script.segments[0].segment_type == "intro"
    assert script.segments[-1].segment_type == "conclusion"
    for i, seg in enumerate(script.segments[1:-1]):
        assert seg.segment_type == "deep_dive"
        assert seg.topic_index == i

    for seg in script.segments:
        assert len(seg.turns) >= 4, f"{seg.segment_type} に turns が足りない"
        speakers = {t.speaker for t in seg.turns}
        assert "A" in speakers and "B" in speakers, f"{seg.segment_type} に A/B が揃っていない"

    assert all(not m.used_fallback for m in script.metrics.values()), (
        f"フォールバックが発生: { {k: v.used_fallback for k, v in script.metrics.items()} }"
    )
