"""number_extractor の単体テスト。"""

from __future__ import annotations

import pytest

from radio_director.phase_d.number_extractor import (
    _extract_from_text,
    extract_numbers,
    is_highly_specific,
)

from tests.phase_d._factories import make_script, make_segment


def _canon(text: str) -> list[str]:
    return [n.canonical for n in _extract_from_text(text, "deep_dive_0")]


def test_percent_unit():
    assert "39.5%" in _canon("感染率は39.5%でした")


def test_bai_unit():
    assert "2.94倍" in _canon("リスクは2.94倍に上昇")


def test_comma_separated_with_unit():
    res = _extract_from_text("対象は3,847件のデータ", "deep_dive_0")
    assert res[0].canonical == "3847件"
    assert res[0].raw == "3,847件"


def test_or_hr_equality():
    res = _extract_from_text("OR=0.207 / HR=2.94", "deep_dive_0")
    canons = [r.canonical for r in res]
    assert "0.207OR" in canons
    assert "2.94HR" in canons


def test_p_value_inequality():
    res = _extract_from_text("p<0.05 で有意", "deep_dive_0")
    assert res[0].canonical == "p<0.05"


def test_time_unit():
    assert "7.0時間" in _canon("睡眠は7.0時間が黄金時間")


def test_oku_unit():
    assert "100億" in _canon("市場規模は100億にのぼる")


def test_highly_specific_decimal_3():
    assert is_highly_specific("0.207") is True
    assert is_highly_specific("23.847") is True


def test_highly_specific_decimal_2():
    """C4 (Step 7): MIN_DECIMAL_PLACES=1 (default) のもとで '0.12' は specific 扱い。

    旧 (Step 7 以前) は 3 桁以上のみ specific だったため False を期待していたが、
    現実の医学・統計数値 (OR=0.85 等) が全て素通りする問題があり、
    閾値を 1 に引き下げた。
    """
    assert is_highly_specific("0.12") is True


def test_highly_specific_million_with_round_suffix():
    """C4 (Step 7): MIN_INTEGER=100 (default) のもとで '2,847,000' も specific 扱い。

    旧 (Step 7 以前) は「末尾 000 でない 100 万以上の整数」のみ specific
    だったため False を期待していたが、現実の n=1,250 / 100名 等が
    全て素通りする問題があり、末尾条件を撤廃し閾値を 100 に引き下げた。
    """
    assert is_highly_specific("2,847,000") is True


def test_highly_specific_million_with_irregular_suffix():
    assert is_highly_specific("2,847,193") is True


def test_highly_specific_below_million():
    """C4 (Step 7): MIN_INTEGER=100 のもとで '847,193' も specific 扱い。"""
    assert is_highly_specific("847,193") is True


def test_extract_numbers_walks_all_segments():
    script = make_script(
        segments=[
            make_segment(
                segment_type="intro",
                topic_index=None,
                title="i",
                turn_texts=[("A", "70%減のだー"), ("B", "ですわ"), ("A", "x"), ("B", "y")],
            ),
            make_segment(
                segment_type="deep_dive",
                topic_index=0,
                title="d0",
                turn_texts=[("A", "OR=0.207のだ"), ("B", "ですわ"), ("A", "x"), ("B", "y")],
            ),
            make_segment(
                segment_type="deep_dive",
                topic_index=1,
                title="d1",
                turn_texts=[("A", "x"), ("B", "y"), ("A", "z"), ("B", "w")],
            ),
            make_segment(
                segment_type="conclusion",
                topic_index=None,
                title="c",
                turn_texts=[("A", "x"), ("B", "y"), ("A", "z"), ("B", "w")],
            ),
        ],
    )
    nums = extract_numbers(script)
    seg_ids = {n.segment_id for n in nums}
    canons = {n.canonical for n in nums}
    assert "intro" in seg_ids
    assert "deep_dive_0" in seg_ids
    assert "70%" in canons
    assert "0.207OR" in canons


def test_extract_skips_isolated_single_digits():
    """単位なし・小数なしの単独「1」「2」などはノイズとして無視。"""
    res = _extract_from_text("Aさん 1 番目 2 番目", "intro")
    assert res == []


def test_or_hr_takes_precedence_over_decimal():
    """OR=0.207 が「0.207」として二重計上されないこと。"""
    res = _extract_from_text("OR=0.207 で、これは highly_specific", "deep_dive_0")
    canons = [r.canonical for r in res]
    assert canons == ["0.207OR"]
