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
    # C6 修正後: 旧 directive "[AAA]/[AA]/[A]/[B]" は廃止。
    # 新 directive: 本文 inline は [src=N] のみ、tier/confidence は本文に書かない。
    return all(
        s in prompt
        for s in [
            "ずんだもん",
            "四国めたん",
            "提供された key_claims から選んで",
            "[src=N]",
            "tier/confidence は台本本文に書かない",
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
    # C6 修正後: key_claims inline は [src=N] のみ。tier/confidence は別ブロック。
    for claim in target.key_claims:
        assert f"[src={claim.source_idx}] {claim.text}" in prompt
        # tier/confidence は metadata block にだけ存在する
        assert f"src={claim.source_idx}: tier={claim.source_tier}, confidence={claim.confidence}" in prompt
    # C6 回帰: 旧 inline 形式 [src=N][TIER][confidence] は登場しないこと
    for claim in target.key_claims:
        assert f"[src={claim.source_idx}][{claim.source_tier}]" not in prompt


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


def test_conclusion_prior_includes_full_turns():
    """backlog §6: 旧 4 ターン truncation 撤廃、全 turn を full text として埋め込む。"""
    show = make_show_spec(n_topics=3)
    long_turns = [
        DialogTurn(speaker="A" if i % 2 == 0 else "B", text=f"発話{i}")
        for i in range(20)
    ]
    seg = ScriptSegment(
        segment_type="intro", title="t", turns=long_turns
    )
    prompt = build_conclusion_prompt(show, [seg])
    # 旧契約 (4 ターンで打ち切り) を撤廃: 全 20 ターンが prompt に含まれる
    assert "発話0" in prompt
    assert "発話3" in prompt
    assert "発話4" in prompt
    assert "発話19" in prompt


# ---------------------------------------------------------------------------
# backlog §6: deep_dive_prompt が prior_segments を full text で受け取る
# ---------------------------------------------------------------------------


def test_deep_dive_prompt_accepts_no_prior_segments():
    """prior_segments を省略しても従来通り動く (intro 直後等の最初の deep_dive)。"""
    show = make_show_spec(n_topics=3)
    prompt = build_deep_dive_prompt(show, topic_index=0)
    assert _common_directives_present(prompt)
    assert show.topics[0].title in prompt
    # prior ブロックは生成されない (section header の有無で判定)
    assert "# これまでの台本" not in prompt
    assert "[intro]" not in prompt


def test_deep_dive_prompt_includes_prior_full_text():
    """prior_segments の全 turn を full text で埋め込む (4 ターン制限なし)。"""
    show = make_show_spec(n_topics=3)
    intro_seg = ScriptSegment(
        segment_type="intro",
        title="イントロ",
        turns=[
            DialogTurn(speaker="A", text=f"intro発話{i}") for i in range(10)
        ]
        + [DialogTurn(speaker="B", text="締め") for _ in range(2)],
    )
    prompt = build_deep_dive_prompt(
        show, topic_index=1, prior_segments=[intro_seg]
    )
    assert _common_directives_present(prompt)
    assert "[intro]" in prompt
    # 4 ターン制限なし: 全 12 ターンが含まれる
    assert "intro発話0" in prompt
    assert "intro発話9" in prompt
    # 自然なブリッジ指示が含まれる
    assert "ブリッジ" in prompt or "繰り返しを避ける" in prompt


def test_deep_dive_prompt_accumulates_multiple_priors():
    """intro + deep_dive_0 を context として渡すと両方が prompt に含まれる。"""
    show = make_show_spec(n_topics=3)
    intro_seg = ScriptSegment(
        segment_type="intro",
        title="イントロ",
        turns=[DialogTurn(speaker="A", text="i" + str(i)) for i in range(4)],
    )
    dd0_seg = ScriptSegment(
        segment_type="deep_dive",
        topic_index=0,
        title=show.topics[0].title,
        turns=[DialogTurn(speaker="B", text="d" + str(i)) for i in range(4)],
    )
    prompt = build_deep_dive_prompt(
        show, topic_index=1, prior_segments=[intro_seg, dd0_seg]
    )
    assert "[intro]" in prompt
    assert f"[topic 1: {show.topics[0].title}]" in prompt
    assert "i0" in prompt
    assert "d3" in prompt
