"""Phase A→B→C→D end-to-end の実機 LLM 統合テスト。

CI ではスキップ。手動検証は次で実行:
    RADIO_DIRECTOR_INTEGRATION=1 pytest tests/phase_d/test_integration_llm.py -v -s

所要時間想定: Phase B ~120s + Phase C ~120s + Phase D ~30s ≒ 4-5 分。
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
from radio_director.phase_c.conductor import conduct
from radio_director.phase_d.verifier import verify

BRIEF_PATH = Path(__file__).parent.parent / "data" / "research_brief_sample.json"

pytestmark = pytest.mark.skipif(
    not os.environ.get("RADIO_DIRECTOR_INTEGRATION"),
    reason="LLM 統合テスト (RADIO_DIRECTOR_INTEGRATION=1 で有効化)",
)


def test_phase_a_to_d_end_to_end(caplog):
    caplog.set_level(logging.INFO)

    client = LLMClient.from_env()
    cleaned = decode(
        ResearchBrief.model_validate_json(BRIEF_PATH.read_text(encoding="utf-8"))
    )

    started = time.monotonic()
    show_spec = plan_show(cleaned, client=client)
    phase_b_elapsed = time.monotonic() - started

    started_c = time.monotonic()
    script = conduct(show_spec, client=client)
    phase_c_elapsed = time.monotonic() - started_c

    started_d = time.monotonic()
    verified = verify(script, cleaned, client=client)
    phase_d_elapsed = time.monotonic() - started_d

    print(f"\n[§24] phase_b_elapsed_sec = {phase_b_elapsed:.1f}")
    print(f"[§24] phase_c_elapsed_sec = {phase_c_elapsed:.1f}")
    print(f"[§24] phase_d_elapsed_sec = {phase_d_elapsed:.1f}")
    print(f"[§24] total_numbers_extracted     = {verified.metrics.total_numbers_extracted}")
    print(f"[§24] matched_to_structured_facts = {verified.metrics.matched_to_structured_facts}")
    print(f"[§24] matched_ratio               = {verified.metrics.matched_ratio:.3f}")
    print(f"[§24] highly_specific_count       = {verified.metrics.highly_specific_count}")
    print(f"[§24] highly_specific_unmatched   = {verified.metrics.highly_specific_unmatched}")
    print(f"[§24] false_positive_candidates   = {verified.metrics.false_positive_candidates}")
    print(f"[§24] citation_tags_total         = {verified.metrics.citation_tags_total}")
    print(f"[§24] citation_tags_normalized    = {verified.metrics.citation_tags_normalized}")
    print(f"[§24] citation_tags_inconsistent  = {verified.metrics.citation_tags_inconsistent}")
    print(f"[§24] warnings_count = {len(verified.warnings)}")
    for w in verified.warnings[:10]:
        print(f"   - {w.code} @ {w.location}: {w.message[:80]}")
    print(f"[§24] metadata.title         = {verified.metadata.title!r}")
    print(f"[§24] metadata.description   = {verified.metadata.description[:80]!r}...")
    print(f"[§24] metadata.hashtags      = {verified.metadata.hashtags}")
    for c in verified.metadata.chapters:
        print(f"   chapter {c.timestamp:>8s}  {c.title}")

    assert verified.metrics.total_numbers_extracted >= 0
    assert 0.0 <= verified.metrics.matched_ratio <= 1.0
    assert len(verified.metadata.chapters) == len(script.segments)
    assert len(verified.metadata.hashtags) >= 3
