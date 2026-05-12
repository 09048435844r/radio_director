"""C3 (Step 8): source_attribution_validator のテスト。

Phase B が key_claims で当てずっぽうな source_idx を割り当てる挙動を
deterministic に検出する。
"""

from __future__ import annotations

from radio_director import config
from radio_director.phase_d.source_attribution_validator import (
    _extract_number_tokens,
    check_source_attribution,
)

from tests.phase_d._factories import make_cleaned_research, make_show_spec


def _make_show_with_claim_text(text: str, source_idx: int = 1):
    """key_claim 1 件だけ手動で差し替えた ShowSpec を作る。"""
    show = make_show_spec(n_topics=3)
    # 最初の topic の最初の claim を差し替え
    show.topics[0].key_claims[0] = show.topics[0].key_claims[0].model_copy(
        update={"text": text, "source_idx": source_idx}
    )
    return show


# ─── 数値抽出 ──────────────────────────────────────────────────────
def test_extract_numbers_basic():
    tokens = _extract_number_tokens("15% 減少、n=1,250 のコホート")
    assert "15" in tokens
    assert "1,250" in tokens


def test_extract_numbers_decimal():
    tokens = _extract_number_tokens("OR=0.85、HR=1.23")
    assert "0.85" in tokens
    assert "1.23" in tokens


# ─── 整合: SF に存在する数値はミスマッチでない ───────────────────────
def test_attribution_match_via_sf():
    """claim に '39.5%' (=SF key_numbers の値) → ミスマッチなし"""
    cleaned = make_cleaned_research()
    # default で SF.key_numbers に 39.5 がある
    show = _make_show_with_claim_text("感染率は39.5%増加した", source_idx=1)
    warnings = check_source_attribution(show, cleaned)
    assert len(warnings) == 0


# ─── ミスマッチ: SF にも source snippet にも無い ─────────────────────
def test_attribution_mismatch_number():
    """claim に SF にも source にも無い '999%' → source_attribution_mismatch"""
    cleaned = make_cleaned_research()
    show = _make_show_with_claim_text("膝衝撃が 999% 減少", source_idx=1)
    warnings = check_source_attribution(show, cleaned)
    assert any(w.code == "source_attribution_mismatch" for w in warnings)


# ─── tolerance: 近似マッチで整合扱い ────────────────────────────────
def test_attribution_tolerance_match(monkeypatch):
    """claim '39%' vs SF '39.5%' は tolerance 5% 内で整合"""
    monkeypatch.setattr(config, "C3_NUMBER_TOLERANCE_PCT", 5.0)
    cleaned = make_cleaned_research()
    show = _make_show_with_claim_text("感染率は39%増加", source_idx=1)
    warnings = check_source_attribution(show, cleaned)
    assert all(w.code != "source_attribution_mismatch" for w in warnings)


def test_attribution_tolerance_miss(monkeypatch):
    """tolerance を 1% に下げると '39%' vs '39.5%' はミスマッチ"""
    monkeypatch.setattr(config, "C3_NUMBER_TOLERANCE_PCT", 1.0)
    cleaned = make_cleaned_research()
    show = _make_show_with_claim_text("感染率は39%増加", source_idx=1)
    warnings = check_source_attribution(show, cleaned)
    assert any(w.code == "source_attribution_mismatch" for w in warnings)


# ─── source snippet マッチ: SF に無くてもソース本体にあれば OK ────────
def test_attribution_match_via_source_snippet():
    """claim の数値が SF には無いが、claim.source_idx が指すソースの snippet にある"""
    cleaned = make_cleaned_research()
    # source[0].snippet に "77.7%" を埋め込む
    src = cleaned.sources[0]
    cleaned.sources[0] = src.model_copy(
        update={"snippet": "本研究では 77.7% の改善が確認された"}
    )
    show = _make_show_with_claim_text("結果は77.7%だった", source_idx=1)
    warnings = check_source_attribution(show, cleaned)
    assert all(w.code != "source_attribution_mismatch" for w in warnings)


# ─── 範囲外 source_idx は単に SF のみで判定 (citation_normalizer が別途警告) ──
def test_attribution_out_of_range_source_idx():
    """src=99 (範囲外) でも check は走る (SF にだけマッチング)"""
    cleaned = make_cleaned_research()
    show = _make_show_with_claim_text("感染率は39.5%増加", source_idx=99)
    warnings = check_source_attribution(show, cleaned)
    # 39.5 が SF にあるのでミスマッチではない
    assert all(w.code != "source_attribution_mismatch" for w in warnings)


# ─── flag OFF: 全 skip ─────────────────────────────────────────────
def test_attribution_disabled(monkeypatch):
    monkeypatch.setattr(config, "C3_ENABLE", False)
    cleaned = make_cleaned_research()
    show = _make_show_with_claim_text("999%", source_idx=1)
    warnings = check_source_attribution(show, cleaned)
    assert len(warnings) == 0


# ─── entity check (デフォルト OFF) ─────────────────────────────────
def test_entity_check_disabled_by_default():
    """C3_REQUIRE_ENTITY_MATCH=False (default) で entity ミスマッチは warning にならない"""
    cleaned = make_cleaned_research()
    # claim にカタカナの固有名詞候補を入れる (SF.key_entities には無い)
    show = _make_show_with_claim_text(
        "ハーバードメディカルスクールの研究で 39.5% 増加", source_idx=1
    )
    warnings = check_source_attribution(show, cleaned)
    # 数値は SF にあるのでミスマッチではない。entity は OFF なので warning なし
    assert all(w.code != "source_attribution_mismatch" for w in warnings)


def test_entity_check_enabled(monkeypatch):
    """REQUIRE_ENTITY_MATCH=True で entity ミスマッチも warning"""
    monkeypatch.setattr(config, "C3_REQUIRE_ENTITY_MATCH", True)
    cleaned = make_cleaned_research()
    show = _make_show_with_claim_text(
        "ハーバードメディカルスクールの研究", source_idx=1
    )
    warnings = check_source_attribution(show, cleaned)
    # ハーバードメディカルスクール は SF にも source snippet にも無い
    assert any(w.code == "source_attribution_mismatch" for w in warnings)
