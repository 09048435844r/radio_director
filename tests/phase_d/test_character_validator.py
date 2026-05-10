"""character_validator の単体テスト (backlog §8)。

speaker=B が「のだ」語尾を使う致命的口調崩壊と、キャラ名表記揺れの
決定論的検出を確認する。
"""

from __future__ import annotations

from radio_director.phase_d.character_validator import check_character_voice

from tests.phase_d._factories import make_script, make_segment


def _script_with_segment(seg):
    """1 つの異常 segment を含む 5 segment 構成の Script を生成する。"""
    return make_script(
        segments=[
            make_segment(segment_type="intro", topic_index=None, title="イントロ"),
            seg,
            make_segment(segment_type="deep_dive", topic_index=1, title="topic2"),
            make_segment(segment_type="deep_dive", topic_index=2, title="topic3"),
            make_segment(segment_type="conclusion", topic_index=None, title="まとめ"),
        ]
    )


# ---------------------------------------------------------------------------
# wrong_speaker_voice: speaker=B が A 語尾「のだ」を使う (致命的口調崩壊)
# ---------------------------------------------------------------------------


def test_b_uses_noda_suffix_triggers_warning():
    """speaker=B が「のだ」語尾を使うと wrong_speaker_voice 警告。"""
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="t",
        turn_texts=[
            ("A", "驚きなのだー"),
            ("B", "それは興味深いのだ"),  # 致命的: B が A 語尾
            ("A", "そうなのだ"),
            ("B", "ですわね"),
        ],
    )
    script = _script_with_segment(seg)
    warnings = check_character_voice(script)
    codes = [w.code for w in warnings]
    assert "wrong_speaker_voice" in codes
    locs = [w.location for w in warnings if w.code == "wrong_speaker_voice"]
    assert "deep_dive_0" in locs


def test_b_uses_nanoda_suffix_triggers_warning():
    """「なのだ」も検出対象。"""
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="t",
        turn_texts=[
            ("A", "驚きなのだ"),
            ("B", "それは大変なのだ"),  # 致命的
            ("A", "x"),
            ("B", "y"),
        ],
    )
    script = _script_with_segment(seg)
    warnings = check_character_voice(script)
    assert any(w.code == "wrong_speaker_voice" for w in warnings)


def test_b_uses_noda_with_punctuation_triggers_warning():
    """末尾に句読点があっても suffix 判定する (「のだ。」「のだ!」等)。"""
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="t",
        turn_texts=[
            ("A", "x"),
            ("B", "そうなのだ。"),
            ("A", "y"),
            ("B", "本当なのだー！"),
        ],
    )
    script = _script_with_segment(seg)
    warnings = [w for w in check_character_voice(script) if w.code == "wrong_speaker_voice"]
    assert len(warnings) >= 2


def test_b_normal_voice_does_not_trigger():
    """B が「ですわ」「ですね」等の正常な語尾を使う場合は警告なし。"""
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="t",
        turn_texts=[
            ("A", "驚きなのだ"),
            ("B", "それは興味深いですわ"),
            ("A", "そうなのだー"),
            ("B", "実はそうですね"),
        ],
    )
    script = _script_with_segment(seg)
    warnings = check_character_voice(script)
    assert not any(w.code == "wrong_speaker_voice" for w in warnings)


def test_a_uses_desuwa_suffix_triggers_warning():
    """対称性: A が「ですわ」語尾を使うと検出 (本運用では未観測だが対称的に守る)。"""
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="t",
        turn_texts=[
            ("A", "それは面白いですわ"),  # 異常: A が B 語尾
            ("B", "x"),
            ("A", "y"),
            ("B", "z"),
        ],
    )
    script = _script_with_segment(seg)
    assert any(w.code == "wrong_speaker_voice" for w in check_character_voice(script))


def test_a_using_nanoda_freely_is_not_a_violation():
    """A の「なのだ」過剰使用 (30-50% 目安) は Phase C プロンプト目安のみで、Phase D 検出対象外。"""
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="t",
        turn_texts=[
            ("A", "なのだ"),
            ("B", "ですわ"),
            ("A", "なのだ"),
            ("B", "ですわ"),
            ("A", "なのだー"),
        ],
    )
    script = _script_with_segment(seg)
    voice_codes = [w.code for w in check_character_voice(script) if w.code == "wrong_speaker_voice"]
    assert voice_codes == []


# ---------------------------------------------------------------------------
# character_name_corruption: 表記揺れ検出
# ---------------------------------------------------------------------------


def test_corrupted_metan_name_triggers_warning():
    """「四国メタン」「四国メたん」等の表記揺れを検出。"""
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="t",
        turn_texts=[
            ("A", "四国メタンに聞いてみるのだ"),  # 揺れ
            ("B", "それはですわね"),
            ("A", "x"),
            ("B", "y"),
        ],
    )
    script = _script_with_segment(seg)
    codes = [w.code for w in check_character_voice(script)]
    assert "character_name_corruption" in codes


def test_corrupted_zundamon_name_triggers_warning():
    """「ズンダもん」「ずんだ門」等の揺れを検出。"""
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="t",
        turn_texts=[
            ("A", "なのだ"),
            ("B", "ズンダもんが言うにはですわ"),  # 揺れ
            ("A", "x"),
            ("B", "y"),
        ],
    )
    script = _script_with_segment(seg)
    assert any(
        w.code == "character_name_corruption" for w in check_character_voice(script)
    )


def test_canonical_names_do_not_trigger():
    """正規表記「ずんだもん」「四国めたん」は許容、警告なし。"""
    seg = make_segment(
        segment_type="deep_dive",
        topic_index=0,
        title="t",
        turn_texts=[
            ("A", "ずんだもんと話すのだ"),
            ("B", "四国めたんですわ"),
            ("A", "x"),
            ("B", "y"),
        ],
    )
    script = _script_with_segment(seg)
    codes = [w.code for w in check_character_voice(script)]
    assert "character_name_corruption" not in codes


def test_no_violations_yields_empty_warnings():
    """完全に正常な script では警告なし。"""
    script = make_script()  # _factories のデフォルトは "発話0" 等の中立 text
    warnings = check_character_voice(script)
    voice_codes = [w.code for w in warnings if w.code == "wrong_speaker_voice"]
    name_codes = [w.code for w in warnings if w.code == "character_name_corruption"]
    assert voice_codes == []
    assert name_codes == []
