"""runner.run_pipeline の実機 LLM 統合テスト (Step 1 SSOT 化、env-gated)。

CI ではスキップ。手動検証は次で実行:
    RADIO_DIRECTOR_INTEGRATION=1 pytest tests/test_runner_integration_llm.py -v -s

Phase A→B→C→D 全てを実機 LLM で実行し、output/<run_id>/ に 5 artifact が
保存されることを確認する。所要時間想定: ~4 分 (Phase B ~120s + Phase C
並列 ~120s + Phase D ~30s)。

既存 tests/phase_d/test_integration_llm.py はそのまま残す (Append-Only)。
重複統合は v2 別タスクで切り分け。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from radio_director.phase_b.llm_client import LLMClient
from radio_director.runner import run_pipeline

BRIEF_PATH = Path(__file__).parent / "data" / "research_brief_sample.json"

pytestmark = pytest.mark.skipif(
    not os.environ.get("RADIO_DIRECTOR_INTEGRATION"),
    reason="LLM 統合テスト (RADIO_DIRECTOR_INTEGRATION=1 で有効化)",
)


def test_runner_end_to_end_writes_5_artifacts(tmp_path):
    """A→B→C→D を実機 LLM で完走し、5 artifact + phase_logs/ が生成される。"""
    output_root = tmp_path / "output"
    client = LLMClient.from_env()

    started = time.monotonic()
    run_dir = run_pipeline(BRIEF_PATH, output_root=output_root, client=client)
    elapsed = time.monotonic() - started

    print(f"\n[runner-e2e] total_elapsed_sec = {elapsed:.1f}")
    print(f"[runner-e2e] run_dir = {run_dir}")

    assert (run_dir / "cleaned_research.json").is_file()
    assert (run_dir / "show_spec.json").is_file()
    assert (run_dir / "verified_script.json").is_file()
    assert (run_dir / "run_metadata.json").is_file()
    assert (run_dir / "phase_logs").is_dir()

    # VerifiedScript の SSOT 要件確認
    verified = json.loads((run_dir / "verified_script.json").read_text(encoding="utf-8"))
    metadata = verified["metadata"]
    assert metadata["thumbnail_title"]
    assert 1 <= len(metadata["thumbnail_title"]) <= 15
    assert isinstance(metadata["references"], list)
    print(f"[runner-e2e] thumbnail_title = {metadata['thumbnail_title']!r}")
    print(f"[runner-e2e] title           = {metadata['title']!r}")
    print(f"[runner-e2e] hashtags        = {metadata['hashtags']}")
    print(f"[runner-e2e] references      = {len(metadata['references'])} 件")
    for ref in metadata["references"]:
        print(f"  - tier={ref.get('tier')} url={ref.get('url')}")
    print(f"[runner-e2e] chapters        = {len(metadata['chapters'])} 件")
    print(f"[runner-e2e] warnings        = {len(verified['warnings'])} 件")
    print(f"[runner-e2e] metrics         = {verified['metrics']}")

    # ハルシネーション False Positive 0% を維持 (Step 1 確定要件 §4.2)
    metrics = verified["metrics"]
    print(f"[runner-e2e] highly_specific_unmatched = {metrics['highly_specific_unmatched']}")
    print(f"[runner-e2e] false_positive_candidates = {metrics['false_positive_candidates']}")

    # run_metadata 整合
    md = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert md["run_id"] == run_dir.name
    assert md["duration_sec"] >= 0
    assert set(md["phases"].keys()) == {"phase_a", "phase_b", "phase_c", "phase_d"}
