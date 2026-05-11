"""C2: Phase B research_content の数値プレースホルダ置換テスト。

仕様:
- 統計量表記 (n=, p<, OR=, 95%CI 等) → 丸ごと placeholder
- 単位付き数値 ("27mm") → "[出典の数値]mm"
- 裸の数値 ("1,250") → "[出典の数値]"
- 年号 ("2024年") → 保持
- フラグ OFF 時は素通し
"""

from __future__ import annotations

import importlib

from radio_director import config
from radio_director.phase_b.prompt_builder import _strip_numbers_for_phase_b

_PLACEHOLDER = "[出典の数値]"


# ─── 基本: 単位付き数値が placeholder + 単位に置換される ──────────────
def test_unit_number_percent_placeholder():
    s = _strip_numbers_for_phase_b(
        "膝関節への衝撃力が 15-20% 減少", placeholder=_PLACEHOLDER
    )
    assert f"{_PLACEHOLDER}%" in s
    # 元の "15", "20" は残っていないこと
    assert "15" not in s
    assert "20" not in s


def test_unit_number_mm_placeholder():
    s = _strip_numbers_for_phase_b(
        "ソール厚 27mm のシューズ", placeholder=_PLACEHOLDER
    )
    assert f"{_PLACEHOLDER}mm" in s
    assert "27" not in s


def test_unit_number_kmh_excluded_special():
    """km/h は単位リストに含まれていない場合の挙動 (現実装では未対応で OK)。"""
    # 注: 'km/h' は単一トークンとして単位リストに含まれていない。
    # 単位 'km' は単独でマッチするので "15km" は "[placeholder]km" になる。
    s = _strip_numbers_for_phase_b("15km/h で走行", placeholder=_PLACEHOLDER)
    assert f"{_PLACEHOLDER}km" in s


def test_unit_number_n_kg():
    """kg / 個 / 倍 が単位として扱われる。"""
    s = _strip_numbers_for_phase_b(
        "体重 70kg、効果は 2.94倍", placeholder=_PLACEHOLDER
    )
    assert f"{_PLACEHOLDER}kg" in s
    assert f"{_PLACEHOLDER}倍" in s
    assert "2.94" not in s


# ─── 年号は保持される ────────────────────────────────────────────────
def test_year_2024_preserved():
    s = _strip_numbers_for_phase_b(
        "2024年に発表された研究で", placeholder=_PLACEHOLDER
    )
    assert "2024年" in s


def test_year_with_other_numbers_only_year_preserved():
    """同じ文に年号と統計値が混在 → 年号のみ保持、統計値は placeholder。"""
    s = _strip_numbers_for_phase_b(
        "2024年に発表された n=1,250 の研究で 15% 削減", placeholder=_PLACEHOLDER
    )
    assert "2024年" in s
    # n=1,250 全体が placeholder 化されている
    assert "n=1,250" not in s
    # 15% も placeholder 化されている
    assert "15%" not in s
    # placeholder が複数登場すること
    assert s.count(_PLACEHOLDER) >= 2


# ─── 統計量表記 (n=, p<, OR=, 95%CI 等) は丸ごと placeholder ────────
def test_n_equals_placeholder():
    s = _strip_numbers_for_phase_b(
        "コホート研究 (n=1,250) において", placeholder=_PLACEHOLDER
    )
    assert "n=1,250" not in s
    assert "n=" not in s  # 統計量全体が消える
    assert _PLACEHOLDER in s


def test_p_value_placeholder():
    s = _strip_numbers_for_phase_b(
        "有意差 (p<0.05) が確認された", placeholder=_PLACEHOLDER
    )
    assert "p<0.05" not in s
    assert _PLACEHOLDER in s


def test_or_placeholder():
    s = _strip_numbers_for_phase_b(
        "OR=0.85 (95%CI 0.72-0.98) で", placeholder=_PLACEHOLDER
    )
    assert "OR=0.85" not in s
    assert "95%CI" not in s
    # 0.72-0.98 は単独数値として placeholder 化される (-で連結も別個に処理)
    assert "0.72" not in s


def test_hr_placeholder():
    s = _strip_numbers_for_phase_b("HR=1.23 で", placeholder=_PLACEHOLDER)
    assert "HR=1.23" not in s
    assert _PLACEHOLDER in s


# ─── 裸の数値も placeholder ──────────────────────────────────────────
def test_bare_integer_placeholder():
    s = _strip_numbers_for_phase_b(
        "参加者は 100 名のうち", placeholder=_PLACEHOLDER
    )
    # "100" は単位 "名" がつくのでそちら経路
    assert f"{_PLACEHOLDER}名" in s


def test_bare_number_without_unit():
    """単位なしの裸の数値も placeholder。"""
    s = _strip_numbers_for_phase_b("約 1500 を超える", placeholder=_PLACEHOLDER)
    assert "1500" not in s
    assert _PLACEHOLDER in s


# ─── フラグ OFF: 素通し ───────────────────────────────────────────────
def test_flag_off_passthrough(monkeypatch):
    """PHASE_B_STRIP_NUMBERS=False で素通し挙動を確認する。

    build_prompt 経由ではなく直接呼び出しは関数は常に動くため、
    挙動が off になることは build_prompt のテストで担保 (後述)。
    """
    # 関数自体は常に動くべき (フラグは build_prompt のレベルで分岐)
    s = _strip_numbers_for_phase_b("15%", placeholder=_PLACEHOLDER)
    assert s != "15%"  # 関数は常に置換する


# ─── 空入力 ──────────────────────────────────────────────────────────
def test_empty_string():
    assert _strip_numbers_for_phase_b("", placeholder=_PLACEHOLDER) == ""


def test_no_numbers_passthrough():
    s = _strip_numbers_for_phase_b(
        "あの研究は非常に興味深い結果を示しました", placeholder=_PLACEHOLDER
    )
    assert s == "あの研究は非常に興味深い結果を示しました"


# ─── build_prompt 統合: フラグで挙動切り替え ─────────────────────────
def test_build_prompt_with_flag_on(monkeypatch):
    """PHASE_B_STRIP_NUMBERS=True (default) で research_content が strip される。"""
    from tests.phase_d._factories import make_cleaned_research

    cleaned = make_cleaned_research()
    # research_content を明示的に数値を含むテキストに差し替える (immutable Pydantic model)
    cleaned = cleaned.model_copy(
        update={
            "research_content": "膝衝撃が 15% 減少、2024年の研究で n=1,250"
        }
    )

    monkeypatch.setattr(config, "PHASE_B_STRIP_NUMBERS", True)
    from radio_director.phase_b import prompt_builder
    prompt = prompt_builder.build_prompt(cleaned)
    # placeholder が prompt に含まれること
    assert _PLACEHOLDER in prompt
    # 数値が消えている (research_content 部分から)
    # 注: structured_facts セクションの数値は残る (これは structured_facts なので
    #     placeholder 対象外、Phase B が引用すべきソース)
    # research_content 区間を抽出して確認
    rc_start = prompt.find("# 参考情報")
    assert rc_start >= 0
    rc_section = prompt[rc_start:]
    assert "15%" not in rc_section
    assert "n=1,250" not in rc_section
    # 年号は残る (research_content 内)
    assert "2024年" in rc_section


def test_build_prompt_with_flag_off(monkeypatch):
    """PHASE_B_STRIP_NUMBERS=False で素通し。"""
    from tests.phase_d._factories import make_cleaned_research

    cleaned = make_cleaned_research()
    cleaned = cleaned.model_copy(
        update={"research_content": "膝衝撃が 15% 減少"}
    )

    monkeypatch.setattr(config, "PHASE_B_STRIP_NUMBERS", False)
    from radio_director.phase_b import prompt_builder
    prompt = prompt_builder.build_prompt(cleaned)
    rc_start = prompt.find("# 参考情報")
    assert rc_start >= 0
    rc_section = prompt[rc_start:]
    assert "15%" in rc_section
