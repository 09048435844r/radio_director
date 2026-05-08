"""prompt_builder の単体テスト。"""

from __future__ import annotations

from radio_director.models.script import DialogTurn, ScriptSegment
from radio_director.phase_c.prompt_builder import (
    build_conclusion_prompt,
    build_deep_dive_prompt,
    build_intro_prompt,
)

from tests.phase_c._factories import make_show_spec


def _common_directives_present(prompt: str) -> bool:
    return all(
        s in prompt
        for s in [
            "ずんだもん",
            "四国めたん",
            "提供された key_claims から選んで",
            "[AAA]/[AA]/[A]/[B]",
            "再解釈・改変しないでください",
            '"turns"',
            '"speaker"',
        ]
    )


def test_intro_prompt_contains_required_elements():
    show = make_show_spec(n_topics=3)
    prompt = build_intro_prompt(show)
    assert _common_directives_present(prompt)
    assert show.title in prompt
    assert show.angle in prompt
    assert show.hook in prompt
    # 全 topic タイトルが一覧に含まれる
    for t in show.topics:
        assert t.title in prompt


def test_deep_dive_prompt_focuses_on_target_topic():
    show = make_show_spec(n_topics=3)
    prompt = build_deep_dive_prompt(show, topic_index=1)
    assert _common_directives_present(prompt)

    target = show.topics[1]
    assert target.title in prompt
    assert target.hook in prompt
    assert target.tone in prompt
    # key_claims が [src=...][TIER][confidence] 形式で描画される
    for claim in target.key_claims:
        assert f"[src={claim.source_idx}][{claim.source_tier}][{claim.confidence}]" in prompt
        assert claim.text in prompt


def test_deep_dive_prompt_does_not_leak_other_topics_claims():
    """他 topic の key_claims は混入しない (Phase B が curate 済みを尊重)。"""
    show = make_show_spec(n_topics=3)
    prompt = build_deep_dive_prompt(show, topic_index=0)

    other_claims = show.topics[1].key_claims + show.topics[2].key_claims
    for claim in other_claims:
        assert claim.text not in prompt


def test_conclusion_prompt_includes_prior_summary():
    show = make_show_spec(n_topics=3)
    intro_seg = ScriptSegment(
        segment_type="intro",
        title="イントロ",
        turns=[
            DialogTurn(speaker="A", text="イントロ発話A1"),
            DialogTurn(speaker="B", text="イントロ発話B1"),
            DialogTurn(speaker="A", text="イントロ発話A2"),
            DialogTurn(speaker="B", text="イントロ発話B2"),
        ],
    )
    deep_seg = ScriptSegment(
        segment_type="deep_dive",
        topic_index=0,
        title=show.topics[0].title,
        turns=[
            DialogTurn(speaker="A", text="深掘り発話A1"),
            DialogTurn(speaker="B", text="深掘り発話B1"),
            DialogTurn(speaker="A", text="深掘り発話A2"),
            DialogTurn(speaker="B", text="深掘り発話B2"),
        ],
    )

    prompt = build_conclusion_prompt(show, [intro_seg, deep_seg])
    assert _common_directives_present(prompt)
    assert show.conclusion_message in prompt
    assert "イントロ発話A1" in prompt
    assert "深掘り発話B1" in prompt
    assert "[intro]" in prompt
    assert f"[topic 1: {show.topics[0].title}]" in prompt


def test_conclusion_prior_summary_truncates_to_first_4_turns():
    show = make_show_spec(n_topics=3)
    long_turns = [
        DialogTurn(speaker="A" if i % 2 == 0 else "B", text=f"発話{i}")
        for i in range(20)
    ]
    seg = ScriptSegment(
        segment_type="intro", title="t", turns=long_turns
    )
    prompt = build_conclusion_prompt(show, [seg])
    # 発話3 は含まれるが 発話4 以降は含まれない (先頭 4 ターンのみ抜粋)
    assert "発話0" in prompt
    assert "発話3" in prompt
    assert "発話4" not in prompt
    assert "発話19" not in prompt
