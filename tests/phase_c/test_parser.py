"""parser.parse_segment の単体テスト。"""

from __future__ import annotations

import json

import pytest

from radio_director.phase_c.parser import ScriptParseError, parse_segment

from tests.phase_c._factories import make_turns


def _payload(turns=None):
    return json.dumps({"turns": turns or make_turns(4)}, ensure_ascii=False)


def _parse_intro(raw):
    return parse_segment(
        raw, segment_type="intro", topic_index=None, title="イントロ"
    )


def test_parses_clean_payload():
    seg = _parse_intro(_payload())
    assert seg.segment_type == "intro"
    assert seg.title == "イントロ"
    assert len(seg.turns) == 4


def test_strips_think_tags():
    raw = "<think>plan...</think>\n" + _payload()
    seg = _parse_intro(raw)
    assert len(seg.turns) == 4


def test_strips_code_fences():
    raw = "```json\n" + _payload() + "\n```"
    seg = _parse_intro(raw)
    assert len(seg.turns) == 4


def test_extracts_first_object_when_surrounded_by_garbage():
    raw = "前置き...\n" + _payload() + "\n後書き..."
    seg = _parse_intro(raw)
    assert len(seg.turns) == 4


def test_invalid_json_raises():
    with pytest.raises(ScriptParseError):
        _parse_intro("これは JSON ではない")


def test_top_level_array_raises():
    with pytest.raises(ScriptParseError):
        _parse_intro("[1, 2, 3]")


def test_missing_turns_key_raises():
    with pytest.raises(ScriptParseError):
        _parse_intro(json.dumps({"other": "value"}))


def test_invalid_speaker_raises():
    bad = json.dumps(
        {"turns": [{"speaker": "C", "text": "x"}] * 4},
        ensure_ascii=False,
    )
    with pytest.raises(ScriptParseError):
        _parse_intro(bad)


def test_too_few_turns_raises():
    with pytest.raises(ScriptParseError):
        _parse_intro(_payload(make_turns(3)))


def test_propagates_topic_index_for_deep_dive():
    seg = parse_segment(
        _payload(), segment_type="deep_dive", topic_index=2, title="t"
    )
    assert seg.topic_index == 2
    assert seg.segment_type == "deep_dive"
