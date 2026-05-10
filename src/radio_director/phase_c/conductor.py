"""Phase C のオーケストレーション。intro → deep_dive_* → conclusion の完全 sequential。

backlog §6 (2026-05-10): 各 segment が前の全 segment の full text を context
として受け取れるよう、ThreadPoolExecutor 並列実行を撤廃して直列ループに変更。
品質 (連続性・自然なブリッジ) を優先、所要時間は実機並列時の 2-2.5 倍に増加。

  Time →
  ─────────────────────────────────────────────────
  intro      ████
  topic_1          ████   (intro の full text を参照)
  topic_2                ████   (intro + topic_1 を参照)
  topic_3                      ████   (intro + topic_1/2 を参照)
  conclusion                        ████   (全 4 segment を参照)
"""

from __future__ import annotations

import logging
import time

from radio_director.models.script import Script, ScriptSegment, SegmentMetrics
from radio_director.models.show_spec import ShowSpec
from radio_director.phase_b.llm_client import LLMClient
from radio_director.phase_c.segment_generator import generate_segment

logger = logging.getLogger(__name__)


def conduct(
    show_spec: ShowSpec,
    *,
    client: LLMClient | None = None,
    max_attempts: int = 3,
    temperature: float = 0.6,
    max_tokens: int = 3072,
) -> Script:
    """ShowSpec から Script を生成する。intro → deep_dive_* → conclusion の完全 sequential。

    各 segment は **直前までに完成した全 segment の full text** を prior_segments
    として受け取る (backlog §6)。並列実行はしない。
    """
    client = client or LLMClient.from_env()
    n_topics = len(show_spec.topics)
    total = 2 + n_topics  # intro + deep_dive×N + conclusion

    started = time.monotonic()
    completed: list[ScriptSegment] = []
    metrics: dict[str, SegmentMetrics] = {}

    # intro
    intro_seg, intro_m = _run_segment(
        segment_type="intro",
        topic_index=None,
        label="intro",
        done_index=1,
        total=total,
        show_spec=show_spec,
        prior_segments=[],
        client=client,
        max_attempts=max_attempts,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    completed.append(intro_seg)
    metrics["intro"] = intro_m

    # deep_dive × n_topics (各 segment が完成済みの全 segment を prior として受ける)
    for i in range(n_topics):
        seg, m = _run_segment(
            segment_type="deep_dive",
            topic_index=i,
            label=f"deep_dive[{i}]",
            done_index=2 + i,
            total=total,
            show_spec=show_spec,
            prior_segments=list(completed),
            client=client,
            max_attempts=max_attempts,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        completed.append(seg)
        metrics[f"deep_dive_{i}"] = m

    # conclusion
    conc_seg, conc_m = _run_segment(
        segment_type="conclusion",
        topic_index=None,
        label="conclusion",
        done_index=total,
        total=total,
        show_spec=show_spec,
        prior_segments=list(completed),
        client=client,
        max_attempts=max_attempts,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    completed.append(conc_seg)
    metrics["conclusion"] = conc_m

    total_elapsed = time.monotonic() - started
    logger.info("🎬 Phase C total elapsed=%.1fs", total_elapsed)

    return Script(show_spec=show_spec, segments=completed, metrics=metrics)


def _run_segment(
    *,
    segment_type,
    topic_index,
    label: str,
    done_index: int,
    total: int,
    show_spec: ShowSpec,
    prior_segments: list[ScriptSegment],
    client: LLMClient,
    max_attempts: int,
    temperature: float,
    max_tokens: int,
) -> tuple[ScriptSegment, SegmentMetrics]:
    seg, m = generate_segment(
        segment_type=segment_type,
        topic_index=topic_index,
        show_spec=show_spec,
        prior_segments=prior_segments,
        client=client,
        max_attempts=max_attempts,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    logger.info(
        "🧩 segment %s 完了 (%d/%d): chars=%d attempts=%d%s elapsed=%.1fs",
        label,
        done_index,
        total,
        m.output_chars,
        m.attempts,
        " [fallback]" if m.used_fallback else "",
        m.elapsed_sec,
    )
    return seg, m
