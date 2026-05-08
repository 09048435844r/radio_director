"""Phase A→D の統合 runner (Step 1 SSOT 化)。

research_brief.json を入力に Phase A→B→C→D を直列実行し、
~/radio_director/output/<run_id>/ に以下の artifact を保存する:

  cleaned_research.json     (Mac 側監査ログ、Windows 側は読まない)
  show_spec.json            (監査ログ)
  verified_script.json      (★ Windows 側がコピーする SSOT)
  run_metadata.json         (実行時刻・phase 別 token 概算)
  phase_logs/               (各 phase の raw ログ用ディレクトリ)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from radio_director.models.research_brief import ResearchBrief
from radio_director.output import (
    DEFAULT_OUTPUT_ROOT,
    OutputWriter,
    PhaseMetric,
    build_run_id,
    build_run_metadata,
)
from radio_director.phase_a.decoder import decode
from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_b.planner import plan_show
from radio_director.phase_b.prompt_builder import build_prompt as _build_phase_b_prompt
from radio_director.phase_c.conductor import conduct
from radio_director.phase_d.metadata_generator import _build_prompt as _build_phase_d_prompt
from radio_director.phase_d.verifier import verify

logger = logging.getLogger(__name__)


def run_pipeline(
    research_brief_path: Path,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    client: LLMClient | None = None,
) -> Path:
    """Phase A→D を実行し artifact を output/<run_id>/ に保存する。

    Args:
        research_brief_path: research_pipeline 出力の research_brief.json
        output_root: 出力ルート (デフォルト: ~/radio_director/output/)
        client: LLM クライアント (省略時は LLMClient.from_env())

    Returns:
        作成された run_dir のパス (output_root/<run_id>/ または衝突時 _2/_3)
    """
    started_at = datetime.now()
    started_mono = time.monotonic()

    brief_text = research_brief_path.read_text(encoding="utf-8")
    brief = ResearchBrief.model_validate_json(brief_text)
    run_id = build_run_id(brief.theme, now=started_at)
    writer = OutputWriter(run_id, root=output_root)
    logger.info("runner: run_id=%s run_dir=%s", run_id, writer.run_dir)

    client = client or LLMClient.from_env()

    # Phase A
    phase_a_start = time.monotonic()
    cleaned = decode(brief)
    phase_a_elapsed = time.monotonic() - phase_a_start
    writer.save_json("cleaned_research.json", cleaned)

    # Phase B
    phase_b_prompt = _build_phase_b_prompt(cleaned)
    phase_b_start = time.monotonic()
    show_spec = plan_show(cleaned, client=client)
    phase_b_elapsed = time.monotonic() - phase_b_start
    writer.save_json("show_spec.json", show_spec)

    # Phase C
    phase_c_start = time.monotonic()
    script = conduct(show_spec, client=client)
    phase_c_elapsed = time.monotonic() - phase_c_start

    # Phase D
    phase_d_prompt = _build_phase_d_prompt(show_spec)
    phase_d_start = time.monotonic()
    verified = verify(script, cleaned, client=client)
    phase_d_elapsed = time.monotonic() - phase_d_start
    writer.save_json("verified_script.json", verified)

    completed_at = datetime.now()

    phase_c_total_prompt_chars = sum(
        m.prompt_chars for m in script.metrics.values()
    )
    phase_c_total_output_chars = sum(
        m.output_chars for m in script.metrics.values()
    )

    phases: dict[str, PhaseMetric] = {
        "phase_a": {
            "model": "deterministic",
            "tokens_in": 0,
            "tokens_out": 0,
            "elapsed_sec": phase_a_elapsed,
        },
        "phase_b": {
            "model": client.model,
            "tokens_in": len(phase_b_prompt) // 2,
            "tokens_out": 0,  # output_chars は ShowSpec から正確には逆算困難
            "elapsed_sec": phase_b_elapsed,
        },
        "phase_c": {
            "model": client.model,
            "tokens_in": phase_c_total_prompt_chars // 2,
            "tokens_out": phase_c_total_output_chars // 2,
            "elapsed_sec": phase_c_elapsed,
        },
        "phase_d": {
            "model": client.model,
            "tokens_in": len(phase_d_prompt) // 2,
            "tokens_out": 0,  # description/title/hashtags の chars 合算は省略
            "elapsed_sec": phase_d_elapsed,
        },
    }

    writer.save_json(
        "run_metadata.json",
        build_run_metadata(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            phases=phases,
        ),
    )

    total_elapsed = time.monotonic() - started_mono
    logger.info(
        "runner: complete run_id=%s total_elapsed_sec=%.1f phases=A:%.1f B:%.1f C:%.1f D:%.1f",
        run_id,
        total_elapsed,
        phase_a_elapsed,
        phase_b_elapsed,
        phase_c_elapsed,
        phase_d_elapsed,
    )
    return writer.run_dir
