"""C4: highly_specific 判定の拡張テスト + unmatched_as_fp_candidate。

新閾値:
- MIN_INTEGER = 100 (was 1,000,000)
- MIN_DECIMAL_PLACES = 1 (was 3)
- INCLUDE_PERCENT = True
- INCLUDE_STATISTIC_NOTATION = True

新フラグ:
- PHASE_D_UNMATCHED_AS_FP_CANDIDATE = True → false_positive_candidates が
  unmatched 全件になる (legacy: highly_specific_unmatched と同値)。
"""

from __future__ import annotations

import pytest

from radio_director import config
from radio_director.phase_d.number_extractor import is_highly_specific


# ─── C4: 新閾値の挙動 ────────────────────────────────────────────────
def test_c4_integer_100_is_specific():
    """MIN_INTEGER=100 → 100 以上の整数は specific。"""
    assert is_highly_specific("100") is True
    assert is_highly_specific("1250") is True
    assert is_highly_specific("1,250") is True


def test_c4_integer_below_100_not_specific():
    """100 未満は specific でない (誤検出抑制)。"""
    assert is_highly_specific("50") is False
    assert is_highly_specific("99") is False


def test_c4_decimal_1_place_is_specific():
    """MIN_DECIMAL_PLACES=1 → 小数 1 桁以上は specific。"""
    assert is_highly_specific("0.5") is True
    assert is_highly_specific("0.85") is True
    assert is_highly_specific("23.4") is True


def test_c4_percent_is_specific():
    """% 表現は specific。"""
    assert is_highly_specific("15%") is True
    assert is_highly_specific("0.5%") is True
    assert is_highly_specific("100%") is True


def test_c4_statistic_notation_is_specific():
    """n=, OR=, HR=, p<, CI 等の統計量表記は specific。"""
    assert is_highly_specific("OR=0.85") is True
    assert is_highly_specific("HR=1.2") is True
    assert is_highly_specific("n=1250") is True
    assert is_highly_specific("p<0.05") is True
    assert is_highly_specific("95%CI") is True
    assert is_highly_specific("SMD=-0.43") is True


# ─── C4 フラグで挙動切替 (config の動的変更) ─────────────────────────
def test_c4_min_integer_configurable(monkeypatch):
    """MIN_INTEGER を 1000 に上げると 100 は specific でなくなる。"""
    monkeypatch.setattr(config, "PHASE_D_HS_MIN_INTEGER", 1000)
    assert is_highly_specific("100") is False
    assert is_highly_specific("1000") is True


def test_c4_min_decimal_places_configurable(monkeypatch):
    """MIN_DECIMAL_PLACES を 3 に戻すと '0.12' は specific でなくなる。"""
    monkeypatch.setattr(config, "PHASE_D_HS_MIN_DECIMAL_PLACES", 3)
    assert is_highly_specific("0.12") is False
    assert is_highly_specific("0.123") is True


def test_c4_include_percent_off(monkeypatch):
    """INCLUDE_PERCENT=False で '15%' は specific でなくなる (15 < 100 のため)。"""
    monkeypatch.setattr(config, "PHASE_D_HS_INCLUDE_PERCENT", False)
    assert is_highly_specific("15%") is False
    # '100%' は INCLUDE_PERCENT=False で文字列に "%" を含むため decimal/integer regex
    # ではマッチしない (regex は ^-?\d+$ のみ受理) ので False になる。
    # これは現実装の挙動で、新フラグの bisect 用テストとしては OK。
    assert is_highly_specific("100%") is False


def test_c4_include_statistic_notation_off(monkeypatch):
    """INCLUDE_STATISTIC_NOTATION=False で 'OR=0.85' は specific でなくなる
    (0.85 が決定的にマッチするか確認)。"""
    monkeypatch.setattr(config, "PHASE_D_HS_INCLUDE_STATISTIC_NOTATION", False)
    # "OR=0.85" には特別マッチがなくなり、内部の "OR=0.85" 文字列は
    # decimal regex / integer regex どちらにもマッチしないため specific でない
    assert is_highly_specific("OR=0.85") is False


# ─── C4: verifier 統合 (false_positive_candidates に unmatched を積む) ─
def test_c4_unmatched_as_fp_candidate_flag_on():
    """PHASE_D_UNMATCHED_AS_FP_CANDIDATE=True で fp_candidates が unmatched 全件。"""
    from tests.phase_d._factories import make_cleaned_research, make_script, make_segment
    from radio_director.phase_d.verifier import verify
    from unittest.mock import patch
    from radio_director.models.verified_script import VideoMetadata

    cleaned = make_cleaned_research()
    # script に structured_facts に無い数値を含むテキストを入れる
    script = make_script(
        segments=[
            make_segment(
                segment_type="intro",
                topic_index=None,
                title="イントロ",
                turn_texts=[
                    ("A", "新しい数値 50000 を含む"),
                    ("B", "そうですわ"),
                    ("A", "もう一つの数値 200 もあるのだ"),
                    ("B", "確かにありますね"),
                ],
            ),
            make_segment(segment_type="deep_dive", topic_index=0, title="t0"),
            make_segment(segment_type="deep_dive", topic_index=1, title="t1"),
            make_segment(segment_type="deep_dive", topic_index=2, title="t2"),
            make_segment(segment_type="conclusion", topic_index=None, title="まとめ"),
        ]
    )

    from radio_director.models.video_metadata import Chapter

    fake_meta = VideoMetadata(
        title="t",
        thumbnail_title="ttt",
        description="d" * 60,
        hashtags=["#a", "#b", "#c"],
        chapters=[
            Chapter(timestamp="00:00", title="intro"),
            Chapter(timestamp="01:00", title="topic"),
        ],
        references=[],
    )
    with patch(
        "radio_director.phase_d.verifier.generate_metadata", return_value=fake_meta
    ):
        with patch.object(config, "PHASE_D_UNMATCHED_AS_FP_CANDIDATE", True):
            verified = verify(script, cleaned)
            # 50000 は structured_facts に無いので unmatched ≥ 1
            assert verified.metrics.false_positive_candidates >= 1
            # この flag では fp_candidates = unmatched 全件
            assert verified.metrics.false_positive_candidates == verified.metrics.total_numbers_extracted - verified.metrics.matched_to_structured_facts


def test_c4_unmatched_as_fp_candidate_flag_off():
    """PHASE_D_UNMATCHED_AS_FP_CANDIDATE=False で legacy 挙動
    (fp_candidates = highly_specific_unmatched)。"""
    from tests.phase_d._factories import make_cleaned_research, make_script, make_segment
    from radio_director.phase_d.verifier import verify
    from unittest.mock import patch
    from radio_director.models.verified_script import VideoMetadata

    cleaned = make_cleaned_research()
    script = make_script(
        segments=[
            make_segment(
                segment_type="intro",
                topic_index=None,
                title="イントロ",
                turn_texts=[
                    ("A", "新しい数値 50000 を含む"),
                    ("B", "そうですわ"),
                    ("A", "もう一つの数値 200 もあるのだ"),
                    ("B", "確かにありますね"),
                ],
            ),
            make_segment(segment_type="deep_dive", topic_index=0, title="t0"),
            make_segment(segment_type="deep_dive", topic_index=1, title="t1"),
            make_segment(segment_type="deep_dive", topic_index=2, title="t2"),
            make_segment(segment_type="conclusion", topic_index=None, title="まとめ"),
        ]
    )

    from radio_director.models.video_metadata import Chapter

    fake_meta = VideoMetadata(
        title="t",
        thumbnail_title="ttt",
        description="d" * 60,
        hashtags=["#a", "#b", "#c"],
        chapters=[
            Chapter(timestamp="00:00", title="intro"),
            Chapter(timestamp="01:00", title="topic"),
        ],
        references=[],
    )
    with patch(
        "radio_director.phase_d.verifier.generate_metadata", return_value=fake_meta
    ):
        with patch.object(config, "PHASE_D_UNMATCHED_AS_FP_CANDIDATE", False):
            verified = verify(script, cleaned)
            # legacy: fp_candidates == highly_specific_unmatched
            assert verified.metrics.false_positive_candidates == verified.metrics.highly_specific_unmatched
