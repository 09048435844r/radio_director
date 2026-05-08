"""Phase D テスト用の合成データファクトリ。"""

from __future__ import annotations

from typing import Any

from radio_director.models.cleaned_research import CleanedResearch
from radio_director.models.research_brief import ResearchBrief
from radio_director.models.script import (
    DialogTurn,
    Script,
    ScriptSegment,
    SegmentMetrics,
)
from radio_director.models.show_spec import ShowSpec
from radio_director.phase_a.decoder import decode

from tests.phase_a._factories import kn, make_brief


def make_show_spec(*, n_topics: int = 3) -> ShowSpec:
    topics = [
        {
            "title": f"トピック{i + 1}",
            "hook": f"フック{i + 1}",
            "key_claims": [
                {
                    "text": f"claim{i + 1}",
                    "source_idx": i + 1,
                    "source_tier": "AAA",
                    "confidence": "medium",
                }
            ],
            "tone": "驚き",
            "estimated_turns": 14,
        }
        for i in range(n_topics)
    ]
    return ShowSpec.model_validate(
        {
            "title": "テスト番組",
            "thumbnail_title": "テスト番組",
            "hook": "視聴者のフック",
            "angle": "切り口",
            "arc": "導入→深掘り→まとめ",
            "tone": "驚き",
            "topics": topics,
            "conclusion_message": "まとめメッセージ",
        }
    )


def make_segment(
    *,
    segment_type: str = "deep_dive",
    topic_index: int | None = 0,
    title: str = "サンプル",
    turn_texts: list[tuple[str, str]] | None = None,
) -> ScriptSegment:
    turns = (
        [DialogTurn(speaker=s, text=t) for s, t in turn_texts]
        if turn_texts
        else [
            DialogTurn(speaker="A" if i % 2 == 0 else "B", text=f"発話{i}")
            for i in range(4)
        ]
    )
    return ScriptSegment(
        segment_type=segment_type,
        topic_index=topic_index,
        title=title,
        turns=turns,
    )


_DEFAULT_METRICS = SegmentMetrics(
    prompt_chars=0, output_chars=0, elapsed_sec=0.0, attempts=1, used_fallback=False
)


def make_script(
    *,
    show_spec: ShowSpec | None = None,
    segments: list[ScriptSegment] | None = None,
) -> Script:
    show = show_spec or make_show_spec(n_topics=3)
    if segments is None:
        segments = [
            make_segment(segment_type="intro", topic_index=None, title="イントロ"),
            make_segment(segment_type="deep_dive", topic_index=0, title=show.topics[0].title),
            make_segment(segment_type="deep_dive", topic_index=1, title=show.topics[1].title),
            make_segment(segment_type="deep_dive", topic_index=2, title=show.topics[2].title),
            make_segment(segment_type="conclusion", topic_index=None, title="まとめ"),
        ]
    metrics = {
        "intro": _DEFAULT_METRICS,
        "deep_dive_0": _DEFAULT_METRICS,
        "deep_dive_1": _DEFAULT_METRICS,
        "deep_dive_2": _DEFAULT_METRICS,
        "conclusion": _DEFAULT_METRICS,
    }
    return Script(show_spec=show, segments=segments, metrics=metrics)


def make_cleaned_research(
    *,
    sources: list[dict[str, Any]] | None = None,
    key_numbers: list[dict[str, Any]] | None = None,
) -> CleanedResearch:
    if sources is None:
        sources = [
            {
                "title": "AAA #1",
                "url": "https://nature.com/a",
                "domain_score": 90,
                "domain_tier": "AAA",
            },
            {
                "title": "AAA #2",
                "url": "https://pubmed.ncbi.nlm.nih.gov/x",
                "domain_score": 90,
                "domain_tier": "AAA",
            },
            {
                "title": "B #3",
                "url": "https://example.com/c",
                "domain_score": 30,
                "domain_tier": "B",
            },
        ]
    if key_numbers is None:
        key_numbers = [
            kn(1, value="39.5", unit="%", context="dummy"),
            kn(1, value="2.94", unit="倍", context="dummy"),
            kn(2, value="0.207", unit="OR", context="dummy"),
        ] + [kn(1)] * 2  # 5 件にして品質ゲートを通す
    payload = make_brief(sources=sources, key_numbers=key_numbers)
    return decode(ResearchBrief.model_validate(payload))
