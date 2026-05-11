"""C6: Phase C プロンプトの key_claims タグ形式テスト。

修正前: [src=N][TIER][confidence] を inline で渡すと LLM が捏造数値にも
        同タグを echo (関連: 派生発見「key_claims タグ注入が捏造に正当性」)。
修正後: inline は [src=N] のみ。tier/confidence は別 metadata block に分離し、
        プロンプトに「本文には書かない」と明示。
"""

from __future__ import annotations

from radio_director.phase_c.prompt_builder import (
    _format_claim_metadata,
    _format_claims,
    build_deep_dive_prompt,
)

from tests.phase_c._factories import make_show_spec


def test_format_claims_inline_is_src_only():
    """_format_claims の出力は [src=N] のみ。tier/confidence を含まない。"""
    show = make_show_spec(n_topics=3)
    topic = show.topics[0]
    inline = _format_claims(topic)
    for c in topic.key_claims:
        assert f"[src={c.source_idx}]" in inline
        # 旧形式の inline tier/confidence が登場しないこと
        assert f"[{c.source_tier}]" not in inline
        assert f"[{c.confidence}]" not in inline


def test_format_claim_metadata_present():
    """_format_claim_metadata は tier/confidence を含む別ブロックとして整形する。"""
    show = make_show_spec(n_topics=3)
    topic = show.topics[0]
    meta = _format_claim_metadata(topic)
    for c in topic.key_claims:
        assert f"src={c.source_idx}:" in meta
        assert f"tier={c.source_tier}" in meta
        assert f"confidence={c.confidence}" in meta


def test_deep_dive_prompt_has_separate_metadata_block():
    """deep_dive prompt に Claim metadata セクションが含まれ、本文 inline と分離している。"""
    show = make_show_spec(n_topics=3)
    prompt = build_deep_dive_prompt(show, topic_index=0)
    assert "# Claim metadata" in prompt
    assert "本文には書かない" in prompt


def test_deep_dive_prompt_no_legacy_inline_tier():
    """C6 回帰: deep_dive prompt の本文 inline (claim 行) に tier/confidence が
    並走しないこと。
    """
    show = make_show_spec(n_topics=3)
    prompt = build_deep_dive_prompt(show, topic_index=0)
    for claim in show.topics[0].key_claims:
        # 旧形式 "[src=N][AAA][medium]" は登場しない
        assert f"[src={claim.source_idx}][{claim.source_tier}]" not in prompt


def test_header_directive_simplified():
    """共通ヘッダの directive が新形式 ([src=N] のみ) を指示すること。"""
    show = make_show_spec(n_topics=3)
    prompt = build_deep_dive_prompt(show, topic_index=0)
    assert "[src=N]" in prompt
    # 旧 directive は廃止
    assert "[AAA]/[AA]/[A]/[B]" not in prompt


def test_empty_key_claims():
    """key_claims 空の場合の挙動 (整形関数が落ちない)。"""
    show = make_show_spec(n_topics=2)
    # key_claims を強制的に空にする (ShowSpec の min topics=2 制約は保つ)
    show.topics[0].key_claims.clear()
    inline = _format_claims(show.topics[0])
    meta = _format_claim_metadata(show.topics[0])
    assert "該当なし" in inline
    assert "該当なし" in meta
