"""1 segment 分の対話を LLM で生成する。retry + fallback を持つ。

仕様 §13.3: 1 segment 失敗時は exponential backoff でリトライし、
max_attempts 到達後はテンプレートのフォールバック対話で Script を成立させる。
used_fallback フラグで Phase D / 上位コードに不完全を伝える。
"""

from __future__ import annotations

import logging
import time

from radio_director.models.script import (
    DialogTurn,
    ScriptSegment,
    SegmentMetrics,
    SegmentType,
)
from radio_director.models.show_spec import ShowSpec
from radio_director.phase_b.llm_client import LLMClient, LLMRequestError
from radio_director.phase_c.parser import ScriptParseError, parse_segment
from radio_director.phase_c.prompt_builder import (
    build_conclusion_prompt,
    build_deep_dive_prompt,
    build_intro_prompt,
)

logger = logging.getLogger(__name__)


def generate_segment(
    *,
    segment_type: SegmentType,
    topic_index: int | None,
    show_spec: ShowSpec,
    prior_segments: list[ScriptSegment] | None,
    client: LLMClient,
    max_attempts: int = 3,
    temperature: float = 0.6,
    max_tokens: int = 3072,
) -> tuple[ScriptSegment, SegmentMetrics]:
    prompt = _build_prompt(segment_type, topic_index, show_spec, prior_segments)
    title = _resolve_title(segment_type, topic_index, show_spec)

    started = time.monotonic()
    raw_text = ""
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            raw_text = client.generate(
                prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=True,
            )
            seg = parse_segment(
                raw_text,
                segment_type=segment_type,
                topic_index=topic_index,
                title=title,
            )
            return seg, SegmentMetrics(
                prompt_chars=len(prompt),
                output_chars=len(raw_text),
                elapsed_sec=time.monotonic() - started,
                attempts=attempt,
                used_fallback=False,
            )
        except (LLMRequestError, ScriptParseError) as exc:
            last_exc = exc
            logger.warning(
                "⚠️ segment %s/%s attempt %d/%d failed: %s",
                segment_type,
                topic_index,
                attempt,
                max_attempts,
                exc,
            )
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))

    logger.error(
        "❌ segment %s/%s fallback テンプレート適用 (max_attempts=%d, last error: %s)",
        segment_type,
        topic_index,
        max_attempts,
        last_exc,
    )
    seg = _build_fallback_segment(segment_type, topic_index, show_spec)
    return seg, SegmentMetrics(
        prompt_chars=len(prompt),
        output_chars=len(raw_text),
        elapsed_sec=time.monotonic() - started,
        attempts=max_attempts,
        used_fallback=True,
    )


def _build_prompt(
    segment_type: SegmentType,
    topic_index: int | None,
    show_spec: ShowSpec,
    prior_segments: list[ScriptSegment] | None,
) -> str:
    if segment_type == "intro":
        return build_intro_prompt(show_spec)
    if segment_type == "deep_dive":
        if topic_index is None:
            raise ValueError("deep_dive には topic_index が必要です")
        return build_deep_dive_prompt(show_spec, topic_index)
    if segment_type == "conclusion":
        return build_conclusion_prompt(show_spec, prior_segments or [])
    raise ValueError(f"unknown segment_type: {segment_type}")


def _resolve_title(
    segment_type: SegmentType,
    topic_index: int | None,
    show_spec: ShowSpec,
) -> str:
    if segment_type == "intro":
        return f"イントロ: {show_spec.title}"
    if segment_type == "deep_dive":
        assert topic_index is not None
        return show_spec.topics[topic_index].title
    if segment_type == "conclusion":
        return f"まとめ: {show_spec.title}"
    raise ValueError(f"unknown segment_type: {segment_type}")


def _build_fallback_segment(
    segment_type: SegmentType,
    topic_index: int | None,
    show_spec: ShowSpec,
) -> ScriptSegment:
    title = _resolve_title(segment_type, topic_index, show_spec)
    if segment_type == "intro":
        turns = [
            DialogTurn(speaker="A", text=f"今日は「{show_spec.angle}」について話していくのだー"),
            DialogTurn(speaker="B", text=f"ええ、{len(show_spec.topics)} つのポイントで掘り下げますわ"),
            DialogTurn(speaker="A", text="楽しみなのだー"),
            DialogTurn(speaker="B", text="順番に見ていきましょう"),
        ]
    elif segment_type == "deep_dive":
        assert topic_index is not None
        topic = show_spec.topics[topic_index]
        turns = [
            DialogTurn(speaker="A", text=f"「{topic.title}」って気になるのだー"),
            DialogTurn(speaker="B", text=f"そうですわね、{topic.hook} ですの"),
            DialogTurn(speaker="A", text="えー、すごいのだ"),
            DialogTurn(
                speaker="B",
                text="(フォールバック台本: 詳しい解説は次回に譲りますわ)",
            ),
        ]
    else:  # conclusion
        turns = [
            DialogTurn(speaker="A", text="今日はたくさん学んだのだー"),
            DialogTurn(speaker="B", text=f"{show_spec.conclusion_message}"),
            DialogTurn(speaker="A", text="明日から実践するのだー"),
            DialogTurn(speaker="B", text="ぜひ習慣にしてくださいませ"),
        ]
    return ScriptSegment(
        segment_type=segment_type,
        topic_index=topic_index,
        title=title,
        turns=turns,
    )
