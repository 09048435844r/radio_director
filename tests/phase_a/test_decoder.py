"""decoder.decode の単体テスト。"""

from __future__ import annotations

from radio_director.models.research_brief import ResearchBrief
from radio_director.phase_a.decoder import decode

from tests.phase_a._factories import ke, kn, make_brief, sc


def _decode(payload):
    return decode(ResearchBrief.model_validate(payload))


def test_resolves_source_tier_one_based():
    """source_idx=1 が research_sources[0] (AAA) に解決されること。"""
    payload = make_brief(
        key_numbers=[kn(1)] * 5,  # 5件 (品質ゲート通過)
    )
    cleaned = _decode(payload)
    assert cleaned.facts.key_numbers[0].primary_source_tier == "AAA"


def test_resolves_source_tier_for_b_source():
    payload = make_brief(
        key_numbers=[kn(2)] * 5,  # source_idx=2 -> research_sources[1] (B)
    )
    cleaned = _decode(payload)
    assert cleaned.facts.key_numbers[0].primary_source_tier == "B"


def test_unknown_source_idx_falls_back_to_b():
    """範囲外 source_idx は安全側 'B' にフォールバック。"""
    payload = make_brief(
        key_numbers=[kn(1)] * 4 + [kn(99)],  # 99 は存在しない
    )
    cleaned = _decode(payload)
    assert cleaned.facts.key_numbers[-1].primary_source_tier == "B"


def test_needs_review_only_when_highly_specific_and_b_tier():
    payload = make_brief(
        key_numbers=[
            kn(1, flags=["highly_specific"]),  # AAA + flag -> 許容
            kn(2, flags=["highly_specific"]),  # B + flag -> 要警告
            kn(2, flags=[]),  # B + no flag -> 許容
            kn(1, flags=[]),
            kn(1, flags=[]),
        ],
    )
    cleaned = _decode(payload)
    needs_review = [f.needs_review for f in cleaned.facts.key_numbers]
    assert needs_review == [False, True, False, False, False]


def test_text_format_per_category():
    payload = make_brief(
        key_numbers=[kn(1, value="2.94", unit="倍", context="感染率")] * 5,
        key_entities=[ke(1, name="慶應", type="institution", role="研究機関")],
        surprising_claims=[
            sc(1, statement="主張", why_surprising="理由"),
        ],
    )
    cleaned = _decode(payload)
    assert cleaned.facts.key_numbers[0].text == "2.94倍 — 感染率"
    assert cleaned.facts.key_entities[0].text == "慶應 (institution) — 研究機関"
    assert cleaned.facts.surprising_claims[0].text == "主張 (理由)"


def test_raw_dict_preserves_original_fields():
    payload = make_brief(
        key_numbers=[kn(1, cross_validated_sources=[1, 5, 7])] * 5,
    )
    cleaned = _decode(payload)
    raw = cleaned.facts.key_numbers[0].raw
    assert raw["cross_validated_sources"] == [1, 5, 7]
    assert raw["confidence"] == "medium"


def test_passes_through_research_content_and_angle():
    payload = make_brief(key_numbers=[kn(1)] * 5)
    payload["research_content"] = "AAA 本文"
    payload["angle"] = "気になる切り口"
    cleaned = _decode(payload)
    assert cleaned.research_content == "AAA 本文"
    assert cleaned.angle == "気になる切り口"


def test_controversies_pass_through_unchanged():
    controversy = {
        "position_a": "8時間が最適",
        "position_b": "6時間で十分",
        "source_indices": [1, 2],
    }
    payload = make_brief(
        key_numbers=[kn(1)] * 5,
        controversies=[controversy],
    )
    cleaned = _decode(payload)
    assert len(cleaned.facts.controversies) == 1
    assert cleaned.facts.controversies[0].position_a == "8時間が最適"
