"""prompt_builder.build_prompt の単体テスト。"""

from __future__ import annotations

from radio_director.models.research_brief import ResearchBrief
from radio_director.phase_a.decoder import decode
from radio_director.phase_b.prompt_builder import build_prompt

from tests.phase_a._factories import kn, ke, sc, make_brief


def _decode(payload):
    return decode(ResearchBrief.model_validate(payload))


def test_prompt_contains_required_directives():
    cleaned = _decode(make_brief(key_numbers=[kn(1)] * 5))
    prompt = build_prompt(cleaned)

    # §19 の必須要件
    assert "数値・固有名詞・統計を引用する場合は「主要な事実」セクションから選んで" in prompt
    # §16 注意事項4
    assert "再解釈・改変しないでください" in prompt
    # 出典タグ規約
    assert "[AAA]/[AA]/[A]/[B]" in prompt
    # ディレクター役の宣言
    assert "ラジオ番組ディレクター" in prompt


def test_prompt_contains_theme_and_angle():
    cleaned = _decode(
        make_brief(
            key_numbers=[kn(1)] * 5,
            extras={"theme": "ねむりの科学", "angle": "切り口テスト"},
        )
    )
    prompt = build_prompt(cleaned)
    assert "ねむりの科学" in prompt
    assert "切り口テスト" in prompt


def test_prompt_includes_fact_categories():
    cleaned = _decode(
        make_brief(
            key_numbers=[kn(1)] * 5,
            key_entities=[ke(1)],
            surprising_claims=[sc(1)],
        )
    )
    prompt = build_prompt(cleaned)
    assert "## key_numbers" in prompt
    assert "## key_entities" in prompt
    assert "## surprising_claims" in prompt
    assert "## controversies" in prompt


def _fact_lines(prompt: str) -> list[str]:
    return [line for line in prompt.splitlines() if line.startswith("- [src=")]


def test_needs_review_facts_get_review_tag():
    """B tier ソースだけ + highly_specific フラグで needs_review が True になる
    fact が [REVIEW] 付きで描画されること。
    """
    cleaned = _decode(
        make_brief(
            sources=[
                {
                    "title": "B src",
                    "url": "https://example.com",
                    "domain_score": 30,
                    "domain_tier": "B",
                }
            ],
            key_numbers=[kn(1, flags=["highly_specific"])] * 5,
        )
    )
    prompt = build_prompt(cleaned)
    fact_lines = _fact_lines(prompt)
    assert fact_lines, "fact 行が描画されていない"
    assert all("][REVIEW]" in line for line in fact_lines)
    assert all("[highly_specific]" in line for line in fact_lines)


def test_aaa_highly_specific_does_not_get_review_tag():
    """AAA tier + highly_specific は許容なので fact 行に REVIEW タグが付かない。"""
    cleaned = _decode(
        make_brief(
            key_numbers=[kn(1, flags=["highly_specific"])] * 5,
        )
    )
    prompt = build_prompt(cleaned)
    fact_lines = _fact_lines(prompt)
    assert fact_lines
    assert all("][REVIEW]" not in line for line in fact_lines)
    # 一方 highly_specific フラグ自体は描画される
    assert all("[highly_specific]" in line for line in fact_lines)


def test_source_list_uses_one_based_index():
    cleaned = _decode(make_brief(key_numbers=[kn(1)] * 5))
    prompt = build_prompt(cleaned)
    # source 1 と source 2 が両方存在
    assert "[1] AAA" in prompt
    assert "[2] B" in prompt


def test_research_content_is_passed_through():
    payload = make_brief(key_numbers=[kn(1)] * 5)
    payload["research_content"] = "本文の文脈情報をここに入れる"
    cleaned = _decode(payload)
    prompt = build_prompt(cleaned)
    assert "本文の文脈情報をここに入れる" in prompt


def test_json_schema_hint_present():
    cleaned = _decode(make_brief(key_numbers=[kn(1)] * 5))
    prompt = build_prompt(cleaned)
    assert "出力フォーマット" in prompt
    assert '"topics"' in prompt
    assert '"conclusion_message"' in prompt


def test_empty_categories_render_placeholder():
    cleaned = _decode(make_brief(key_numbers=[kn(1)] * 5))
    prompt = build_prompt(cleaned)
    # surprising_claims / controversies は空なのでプレースホルダ
    assert "(該当なし)" in prompt
