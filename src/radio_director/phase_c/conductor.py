"""Phase C のオーケストレーション。並列 (intro + deep_dive) → 順次 (conclusion)。

仕様 §13.3:
  Time →
  ─────────────────────────────────────────
  intro      ████              (並列開始)
  topic_1    ████              (並列開始)
  topic_2    ████              (並列開始)
  topic_3    ████              (並列開始)
                    ──────
  conclusion          ████     (intro + topics 完了後)
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from radio_director.models.script import Script, ScriptSegment, SegmentMetrics
from radio_director.models.show_spec import ShowSpec
from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_c.segment_generator import generate_segment

logger = logging.getLogger(__name__)


def conduct(
    show_spec: ShowSpec,
    *,
    client: LLMClient | None = None,
    max_workers: int = 4,
    max_attempts: int = 3,
    temperature: float = 0.6,
    max_tokens: int = 3072,
) -> Script:
    """ShowSpec から Script を生成する。intro+deep_dive を並列、conclusion を sequential。"""
    client = client or LLMClient.from_env()
    n_topics = len(show_spec.topics)

    parallel_specs: list[tuple[str, int | None]] = [("intro", None)]
    parallel_specs.extend(("deep_dive", i) for i in range(n_topics))

    parallel_results: dict[tuple[str, int | None], tuple[ScriptSegment, SegmentMetrics]] = {}

    parallel_total = 1 + n_topics
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(
                generate_segment,
                segment_type=stype,
                topic_index=tidx,
                show_spec=show_spec,
                prior_segments=None,
                client=client,
                max_attempts=max_attempts,
                temperature=temperature,
                max_tokens=max_tokens,
            ): (stype, tidx)
            for stype, tidx in parallel_specs
        }
        done = 0
        for fut in as_completed(futures):
            key = futures[fut]
            seg, m = fut.result()
            parallel_results[key] = (seg, m)
            done += 1
            stype, tidx = key
            label = "intro" if stype == "intro" else f"deep_dive[{tidx}]"
            logger.info(
                "🧩 segment %s 完了 (%d/%d): chars=%d attempts=%d%s elapsed=%.1fs",
                label,
                done,
                parallel_total,
                m.output_chars,
                m.attempts,
                " [fallback]" if m.used_fallback else "",
                m.elapsed_sec,
            )

    intro_seg, intro_m = parallel_results[("intro", None)]
    deep_results = [parallel_results[("deep_dive", i)] for i in range(n_topics)]

    parallel_elapsed = time.monotonic() - started
    logger.info(
        "✅ Phase C 並列フェーズ完了: %d segments elapsed=%.1fs",
        parallel_total,
        parallel_elapsed,
    )

    logger.info("🎬 Phase C: conclusion 生成中 (intro+%d topics 完了後)", n_topics)
    conc_seg, conc_m = generate_segment(
        segment_type="conclusion",
        topic_index=None,
        show_spec=show_spec,
        prior_segments=[intro_seg] + [s for s, _ in deep_results],
        client=client,
        max_attempts=max_attempts,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    logger.info(
        "🧩 segment conclusion 完了: chars=%d attempts=%d%s elapsed=%.1fs",
        conc_m.output_chars,
        conc_m.attempts,
        " [fallback]" if conc_m.used_fallback else "",
        conc_m.elapsed_sec,
    )

    total_elapsed = time.monotonic() - started
    logger.info("🎬 Phase C total elapsed=%.1fs", total_elapsed)

    segments = [intro_seg, *(s for s, _ in deep_results), conc_seg]
    metrics: dict[str, SegmentMetrics] = {
        "intro": intro_m,
        **{f"deep_dive_{i}": m for i, (_, m) in enumerate(deep_results)},
        "conclusion": conc_m,
    }
    return Script(show_spec=show_spec, segments=segments, metrics=metrics)
