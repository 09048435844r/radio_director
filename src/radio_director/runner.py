"""Phase A→D の統合 runner (Step 1 SSOT 化)。

research_brief.json を入力に Phase A→B→C→D を直列実行し、
~/radio_director/output/<run_id>/ に以下の artifact を保存する:

  cleaned_research.json     (Mac 側監査ログ、Windows 側は読まない)
  show_spec.json            (監査ログ)
  verified_script.json      (★ Windows 側がコピーする SSOT)
  run_metadata.json         (実行時刻・phase 別 token 概算)
  phase_logs/               (各 phase の raw ログ用ディレクトリ)
  phase_logs/run.log        (本 runner の進捗ログ複製、attach_file_handler)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from radio_director import config as _config
from radio_director.logging_setup import attach_file_handler, configure_logging
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


class QualityGateError(Exception):
    """Phase D quality gate を retry 後も通過できなかった場合に raise (Step 7 C1)."""


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
    configure_logging()

    started_at = datetime.now()
    started_mono = time.monotonic()

    brief_text = research_brief_path.read_text(encoding="utf-8")
    brief = ResearchBrief.model_validate_json(brief_text)
    run_id = build_run_id(brief.theme, now=started_at)
    writer = OutputWriter(run_id, root=output_root)
    attach_file_handler(writer.run_dir)

    logger.info("🚀 radio_director パイプライン開始: %s", brief.theme[:50])
    logger.info("   run_id: %s", run_id)
    logger.info(
        "   research_mode: %s / angle: %s",
        brief.research_mode,
        brief.angle[:40],
    )
    logger.info("   run_dir: %s", writer.run_dir)

    client = client or LLMClient.from_env()

    # Phase A
    logger.info("─── Phase A: DECODE ─────────────────────────")
    phase_a_start = time.monotonic()
    cleaned = decode(brief)
    phase_a_elapsed = time.monotonic() - phase_a_start
    writer.save_json("cleaned_research.json", cleaned)
    logger.info(
        "✅ Phase A 完了: key_numbers=%d key_entities=%d surprising=%d "
        "sources=%d quality=%s warnings=%d elapsed=%.1fs",
        len(cleaned.facts.key_numbers),
        len(cleaned.facts.key_entities),
        len(cleaned.facts.surprising_claims),
        len(cleaned.sources),
        cleaned.quality_report.overall_quality,
        len(cleaned.quality_report.warnings),
        phase_a_elapsed,
    )

    # Phase B
    logger.info("─── Phase B: PLAN (ShowSpec) ────────────────")
    phase_b_prompt = _build_phase_b_prompt(cleaned)
    phase_b_start = time.monotonic()
    show_spec = plan_show(cleaned, client=client)
    phase_b_elapsed = time.monotonic() - phase_b_start
    writer.save_json("show_spec.json", show_spec)
    logger.info(
        "✅ Phase B 完了: title=「%s」 topics=%d elapsed=%.1fs",
        show_spec.title[:30],
        len(show_spec.topics),
        phase_b_elapsed,
    )

    # Phase C
    logger.info("─── Phase C: CONDUCT (segments) ─────────────")
    phase_c_start = time.monotonic()
    script = conduct(show_spec, client=client)
    phase_c_elapsed = time.monotonic() - phase_c_start
    total_chars = sum(len(t.text) for s in script.segments for t in s.turns)
    fallback_count = sum(1 for m in script.metrics.values() if m.used_fallback)
    logger.info(
        "✅ Phase C 完了: segments=%d total_chars=%d fallbacks=%d elapsed=%.1fs",
        len(script.segments),
        total_chars,
        fallback_count,
        phase_c_elapsed,
    )

    # Phase D
    logger.info("─── Phase D: VERIFY (script + metadata) ─────")
    phase_d_prompt = _build_phase_d_prompt(show_spec)
    phase_d_start = time.monotonic()
    verified = verify(script, cleaned, client=client)
    phase_d_elapsed = time.monotonic() - phase_d_start
    logger.info(
        "✅ Phase D 完了: title=「%s」 hashtags=%d chapters=%d "
        "references=%d warnings=%d elapsed=%.1fs",
        verified.metadata.title[:30],
        len(verified.metadata.hashtags),
        len(verified.metadata.chapters),
        len(verified.metadata.references),
        len(verified.warnings),
        phase_d_elapsed,
    )

    # ─── Step 7 C1: production gate (soft gate, retry, hard fail) ─────────
    # matched_ratio が threshold 未満なら Phase B/C を retry (max=N)、
    # それでも未満なら hard fail し verified_script.failed.json として保存。
    gate_threshold = _config.PHASE_D_MATCHED_RATIO_GATE
    retry_enabled = _config.PHASE_D_RETRY_ENABLED
    retry_max = _config.PHASE_D_RETRY_MAX

    retries = 0
    while (
        verified.metrics.matched_ratio < gate_threshold
        and retry_enabled
        and retries < retry_max
    ):
        retries += 1
        logger.warning(
            "🔁 Phase D gate fail (matched_ratio=%.1f%% < %.0f%%) → Phase B/C を retry (%d/%d)",
            verified.metrics.matched_ratio * 100,
            gate_threshold * 100,
            retries,
            retry_max,
        )
        # Phase B/C を再走 (Phase A は decoder で決定論なので再走しない)
        retry_b_start = time.monotonic()
        show_spec = plan_show(cleaned, client=client)
        phase_b_elapsed += time.monotonic() - retry_b_start

        retry_c_start = time.monotonic()
        script = conduct(show_spec, client=client)
        phase_c_elapsed += time.monotonic() - retry_c_start

        retry_d_start = time.monotonic()
        verified = verify(script, cleaned, client=client)
        phase_d_elapsed += time.monotonic() - retry_d_start

        logger.info(
            "🔁 Phase D retry %d 完了: matched_ratio=%.1f%% warnings=%d",
            retries,
            verified.metrics.matched_ratio * 100,
            len(verified.warnings),
        )

    if verified.metrics.matched_ratio < gate_threshold and retry_enabled:
        # hard fail: diagnostic として別名で保存、verified_script.json は出さない
        writer.save_json("verified_script.failed.json", verified)
        logger.error(
            "❌ Phase D gate を retry %d 回後も通過できず: matched_ratio=%.1f%% < %.0f%%。"
            " verified_script.failed.json として保存。",
            retries,
            verified.metrics.matched_ratio * 100,
            gate_threshold * 100,
        )
        raise QualityGateError(
            f"matched_ratio {verified.metrics.matched_ratio:.1%} "
            f"< gate {gate_threshold:.0%} after {retries} retry(ies)"
        )

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
    minutes, seconds = divmod(int(total_elapsed), 60)
    logger.info(
        "✅ パイプライン完了 (所要時間: %d分%d秒) elapsed=%.1fs",
        minutes,
        seconds,
        total_elapsed,
    )
    logger.info("━" * 50)
    logger.info("📊 サマリー:")
    logger.info("   theme            : %s", brief.theme[:50])
    logger.info("   run_id           : %s", run_id)
    logger.info("   segments         : %d 件", len(script.segments))
    logger.info("   total_chars      : %s 文字", f"{total_chars:,}")
    logger.info("   warnings         : %d 件", len(verified.warnings))
    logger.info(
        "   phase_a/b/c/d    : %.1fs / %.1fs / %.1fs / %.1fs",
        phase_a_elapsed,
        phase_b_elapsed,
        phase_c_elapsed,
        phase_d_elapsed,
    )
    logger.info("   所要時間         : %d分%d秒", minutes, seconds)
    logger.info("   出力ディレクトリ : %s", writer.run_dir)
    logger.info("━" * 50)
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
