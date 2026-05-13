"""P1 (Step 8 v2): 数値マッチャーのトークン化正規化テスト。

"1000 億" (script) と "1000億パラメータ" (structured_facts) が
matched 判定されることを検証する。
"""

from __future__ import annotations

from radio_director import config
from radio_director.phase_d.hallucination_detector import (
    _canonicalize,
    _normalize_canonical,
    build_fact_index,
    detect_hallucinations,
)
from radio_director.phase_d.number_extractor import ExtractedNumber

from tests.phase_d._factories import make_cleaned_research


# ─── _normalize_canonical 単体 ────────────────────────────────────
def test_normalize_strips_spaces():
    assert _normalize_canonical("1000 億") == "1000億"
    assert _normalize_canonical("1,000 億") == "1000億"


def test_normalize_strips_units():
    """日本語単位語が剥がされる"""
    assert _normalize_canonical("1000億パラメータ") == "1000億"
    assert _normalize_canonical("1250名") == "1250"
    assert _normalize_canonical("82施設") == "82"


def test_normalize_full_width_to_half():
    """全角数字が半角に正規化される"""
    assert _normalize_canonical("１０００億") == "1000億"


def test_normalize_keeps_percent():
    """% は単位として保持 (15% != 15)"""
    assert _normalize_canonical("15%") == "15%"


def test_normalize_keeps_mm():
    """mm 等の物理単位は保持"""
    assert _normalize_canonical("27mm") == "27mm"


def test_normalize_empty_passthrough():
    assert _normalize_canonical("") == ""


# ─── build_fact_index で正規化キーも登録される ────────────────────
def test_fact_index_includes_normalized_keys():
    """SF に "1000" / unit="億パラメータ" がある場合、index に "1000億" も登録"""
    cleaned = make_cleaned_research()
    # default cleaned_research を改造: key_numbers[0] を "1000億パラメータ" に
    fact = cleaned.facts.key_numbers[0]
    new_raw = dict(fact.raw)
    new_raw["value"] = "1000"
    new_raw["unit"] = "億パラメータ"
    cleaned.facts.key_numbers[0] = fact.model_copy(update={"raw": new_raw})

    index = build_fact_index(cleaned)
    # 旧 canonical
    assert "1000億パラメータ" in index
    # P1: 正規化キー (パラメータ剥がし) も登録される
    assert "1000億" in index


# ─── detect_hallucinations で正規化マッチが効く ─────────────────────
def test_detect_normalized_match():
    """script 側 "1000 億" が SF 側 "1000億パラメータ" にマッチする"""
    cleaned = make_cleaned_research()
    fact = cleaned.facts.key_numbers[0]
    new_raw = dict(fact.raw)
    new_raw["value"] = "1000"
    new_raw["unit"] = "億パラメータ"
    cleaned.facts.key_numbers[0] = fact.model_copy(update={"raw": new_raw})
    fact_index = build_fact_index(cleaned)

    # script から抽出された数値 (number_extractor の output 模擬)
    extracted = [
        ExtractedNumber(
            canonical="1000億",
            raw="1000 億",
            segment_id="deep_dive_0",
            is_highly_specific=False,
        )
    ]
    stats, warnings = detect_hallucinations(extracted, fact_index)
    assert stats.matched == 1
    assert stats.unmatched == 0


def test_detect_normalized_match_via_value_only():
    """SF 側 value="1250" unit="名" → script "1250" がマッチする (P1 value_only キー)"""
    cleaned = make_cleaned_research()
    fact = cleaned.facts.key_numbers[0]
    new_raw = dict(fact.raw)
    new_raw["value"] = "1250"
    new_raw["unit"] = "名"
    cleaned.facts.key_numbers[0] = fact.model_copy(update={"raw": new_raw})
    fact_index = build_fact_index(cleaned)

    extracted = [
        ExtractedNumber(
            canonical="1250",
            raw="1250",
            segment_id="deep_dive_0",
            is_highly_specific=True,
        )
    ]
    stats, _w = detect_hallucinations(extracted, fact_index)
    assert stats.matched == 1


def test_detect_no_false_match_different_value():
    """1000億 (SF) と 1兆 (script) はマッチしない"""
    cleaned = make_cleaned_research()
    fact = cleaned.facts.key_numbers[0]
    new_raw = dict(fact.raw)
    new_raw["value"] = "1000"
    new_raw["unit"] = "億"
    cleaned.facts.key_numbers[0] = fact.model_copy(update={"raw": new_raw})
    fact_index = build_fact_index(cleaned)

    extracted = [
        ExtractedNumber(
            canonical="1兆",
            raw="1兆",
            segment_id="deep_dive_0",
            is_highly_specific=False,
        )
    ]
    stats, _w = detect_hallucinations(extracted, fact_index)
    # 1000億 != 1兆 → unmatched
    assert stats.matched == 0
    assert stats.unmatched == 1


# ─── flag OFF で legacy 挙動 ─────────────────────────────────────
def test_normalization_disabled_legacy(monkeypatch):
    """PHASE_D_NUMBER_NORMALIZATION_ENABLED=False で legacy (mismatch)"""
    monkeypatch.setattr(config, "PHASE_D_NUMBER_NORMALIZATION_ENABLED", False)
    cleaned = make_cleaned_research()
    fact = cleaned.facts.key_numbers[0]
    new_raw = dict(fact.raw)
    new_raw["value"] = "1000"
    new_raw["unit"] = "億パラメータ"
    cleaned.facts.key_numbers[0] = fact.model_copy(update={"raw": new_raw})
    fact_index = build_fact_index(cleaned)

    extracted = [
        ExtractedNumber(
            canonical="1000億",
            raw="1000 億",
            segment_id="deep_dive_0",
            is_highly_specific=False,
        )
    ]
    stats, _w = detect_hallucinations(extracted, fact_index)
    # legacy: 1000億 != 1000億パラメータ → unmatched
    assert stats.matched == 0
    assert stats.unmatched == 1
