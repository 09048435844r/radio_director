"""DialogTurn / ScriptSegment / Script の Pydantic 検証。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from radio_director.models.script import (
    DialogTurn,
    Script,
    ScriptSegment,
    SegmentMetrics,
)

from tests.phase_c._factories import make_show_spec, make_turns


def _segment(seg_type="deep_dive", topic_index=0, turns=None):
    return ScriptSegment(
        segment_type=seg_type,
        topic_index=topic_index,
        title="サンプルタイトル",
        turns=turns if turns is not None else make_turns(4),
    )


def test_dialog_turn_invalid_speaker_raises():
    with pytest.raises(ValidationError):
        DialogTurn.model_validate({"speaker": "C", "text": "..."})


def test_segment_min_turns_raises():
    with pytest.raises(ValidationError):
        ScriptSegment(
            segment_type="intro",
            title="t",
            turns=make_turns(3),  # 4 未満
        )


def test_segment_extra_fields_ignored():
    seg = ScriptSegment.model_validate(
        {
            "segment_type": "intro",
            "title": "t",
            "turns": make_turns(4),
            "bogus": "ignored",
        }
    )
    assert not hasattr(seg, "bogus")


def test_invalid_segment_type_raises():
    with pytest.raises(ValidationError):
        ScriptSegment.model_validate(
            {"segment_type": "unknown", "title": "t", "turns": make_turns(4)}
        )


def test_script_segments_too_few_raises():
    show = make_show_spec(n_topics=3)
    metrics = SegmentMetrics(
        prompt_chars=0, output_chars=0, elapsed_sec=0.0, attempts=1, used_fallback=False
    )
    with pytest.raises(ValidationError):
        Script(
            show_spec=show,
            segments=[_segment(seg_type="intro", topic_index=None)],  # 1 件
            metrics={"intro": metrics},
        )


def test_script_segments_too_many_raises():
    show = make_show_spec(n_topics=3)
    metrics = SegmentMetrics(
        prompt_chars=0, output_chars=0, elapsed_sec=0.0, attempts=1, used_fallback=False
    )
    with pytest.raises(ValidationError):
        Script(
            show_spec=show,
            segments=[_segment()] * 7,  # 7 件
            metrics={"x": metrics},
        )


def test_well_formed_script():
    show = make_show_spec(n_topics=3)
    metrics = SegmentMetrics(
        prompt_chars=10, output_chars=20, elapsed_sec=1.5, attempts=1, used_fallback=False
    )
    script = Script(
        show_spec=show,
        segments=[
            _segment(seg_type="intro", topic_index=None),
            _segment(seg_type="deep_dive", topic_index=0),
            _segment(seg_type="deep_dive", topic_index=1),
            _segment(seg_type="deep_dive", topic_index=2),
            _segment(seg_type="conclusion", topic_index=None),
        ],
        metrics={
            "intro": metrics,
            "deep_dive_0": metrics,
            "deep_dive_1": metrics,
            "deep_dive_2": metrics,
            "conclusion": metrics,
        },
    )
    assert len(script.segments) == 5
    assert script.metrics["deep_dive_1"].elapsed_sec == 1.5
