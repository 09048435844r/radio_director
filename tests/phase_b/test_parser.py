"""parser.parse_show_spec の単体テスト。"""

from __future__ import annotations

import json

import pytest

from radio_director.phase_b.parser import ShowSpecParseError, parse_show_spec

from tests.phase_b._factories import make_show_spec


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_parses_clean_json():
    show = parse_show_spec(_json(make_show_spec()))
    assert show.title == "寝不足が免疫を壊す？"


def test_strips_think_tags():
    raw = (
        "<think>let me think...\nstep1\nstep2</think>\n"
        + _json(make_show_spec())
    )
    show = parse_show_spec(raw)
    assert show.title == "寝不足が免疫を壊す？"


def test_strips_code_fences():
    raw = "```json\n" + _json(make_show_spec()) + "\n```"
    show = parse_show_spec(raw)
    assert show.title == "寝不足が免疫を壊す？"


def test_extracts_first_json_object_when_surrounded_by_garbage():
    raw = "前置きテキスト...\n\n" + _json(make_show_spec()) + "\n\n後書き"
    show = parse_show_spec(raw)
    assert show.title == "寝不足が免疫を壊す？"


def test_invalid_json_raises():
    with pytest.raises(ShowSpecParseError):
        parse_show_spec("これは JSON ではない")


def test_top_level_array_raises():
    with pytest.raises(ShowSpecParseError):
        parse_show_spec("[1, 2, 3]")


def test_schema_violation_raises():
    """JSON は valid だが ShowSpec として無効 (topics 0件)。"""
    bad = make_show_spec(topics=[])
    with pytest.raises(ShowSpecParseError):
        parse_show_spec(_json(bad))


def test_combined_think_and_fences():
    raw = (
        "<think>plan...</think>\n```json\n"
        + _json(make_show_spec())
        + "\n```"
    )
    show = parse_show_spec(raw)
    assert show.title == "寝不足が免疫を壊す？"
