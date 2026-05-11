"""segment ごとのプロンプトを組み立てる。

intro / deep_dive / conclusion で異なるテンプレートを使うが、共通ヘッダ
（キャラクター設定・共通ルール）と共通フッタ（出力 JSON スキーマ）は
ヘルパで共有する。仕様 §13.2 / §13.3 / §22.4 / §23 を参照。
"""

from __future__ import annotations

from radio_director.models.script import ScriptSegment
from radio_director.models.show_spec import ShowSpec, TopicSpec

_HEADER = """あなたはラジオ番組の対話台本を書く脚本家です。

# 出演者
- A (ずんだもん): 好奇心旺盛、視聴者代表。
  * 語尾は「〜なのだ」「〜のだ」を使うが、**全ターンの 30-50% 程度に抑える**。
    残りは「〜だね」「〜だよ」「〜だなあ」「〜だろう」等で変化をつける。
  * 1 ターン内で「のだ」を 2 回以上重ねない。
- B (四国めたん): 解説役、専門知識を分かりやすく伝える。
  * 語尾は「〜ですわ」「〜ですわね」を主軸に、「〜のですよ」「〜ですね」
    「〜ますの」も混ぜて単調にしない。
  * **絶対禁止: 「〜のだ」「〜なのだ」「〜のだー」等のずんだもん語尾を使わない。**
    これらは A 専用であり、B が使うと致命的な口調崩壊になる。

# キャラ名表記ルール
- 本文中でキャラに言及する場合は **「ずんだもん」「四国めたん」の正規表記のみ**。
- 表記揺れ禁止例: 「四国メタン」「四国メたん」「ズンダもん」「ずんだ門」等。
  カタカナ・ひらがなを混ぜたり当て字を作ったりしないこと。

# 共通ルール
- 数値・固有名詞・統計を引用する場合は提供された key_claims から選んでください
- **台本本文中の引用タグは `[src=N]` 形式のみ**を使用してください
  (例: 「研究によると... [src=3]」)
- **`[AAA]` `[medium]` 等の tier/confidence は台本本文に書かないでください**
  (Claim metadata セクションは内部参照用であり、本文には反映しない)
- 提供されていない情報は絶対に補足しないでください
- 切り口（angle）は与えられたものをそのまま尊重し、再解釈・改変しないでください
- A と B が交互に話す自然な対話の流れにしてください
"""

_FOOTER = """
# 出力フォーマット (JSON、以下のスキーマに厳密に従うこと)
{
  "turns": [
    {"speaker": "A", "text": "対話の発話内容..."},
    {"speaker": "B", "text": "対話の発話内容..."}
  ]
}
"""


def build_intro_prompt(show_spec: ShowSpec) -> str:
    topics_list = "\n".join(
        f"  {i + 1}. {t.title}" for i, t in enumerate(show_spec.topics)
    )
    body = f"""
# あなたの仕事
番組のイントロ（最初の 2 分）を A と B の対話で書いてください。
- 視聴者の関心を一気に掴むフックから入る
- 番組タイトル・angle に触れる
- これから扱う {len(show_spec.topics)} つのトピックを軽く紹介する
- 4-8 ターンが目安

# 番組情報
title: {show_spec.title}
angle: {show_spec.angle}
hook: {show_spec.hook}
arc: {show_spec.arc}
tone: {show_spec.tone}

# 扱うトピック
{topics_list}
"""
    return _HEADER + body + _FOOTER


def build_deep_dive_prompt(
    show_spec: ShowSpec,
    topic_index: int,
    prior_segments: list[ScriptSegment] | None = None,
) -> str:
    topic = show_spec.topics[topic_index]
    prior_block = _format_prior_block(prior_segments or [])
    body = f"""
# あなたの仕事
トピック「{topic.title}」を A と B の対話で深掘りしてください（7-8 分相当）。
- フック「{topic.hook}」から始める
- 提供された key_claims を必ず引用する（出典タグ付き）
- トピックのトーン: {topic.tone}
- {topic.estimated_turns} ターン前後を目安に、12-18 ターンの範囲で
- これまでの台本の流れを踏まえ、自然なブリッジから入る（同じ話題の繰り返しを避ける）

# 番組コンテキスト
title: {show_spec.title}
angle: {show_spec.angle}

# トピック詳細
title: {topic.title}
hook: {topic.hook}
tone: {topic.tone}

# key_claims (引用は必ずここから、本文中は [src=N] 形式のみ使用)
{_format_claims(topic)}

# Claim metadata (内部参照用、本文には書かないでください)
{_format_claim_metadata(topic)}
{prior_block}"""
    return _HEADER + body + _FOOTER


def build_conclusion_prompt(
    show_spec: ShowSpec, prior_segments: list[ScriptSegment]
) -> str:
    prior_block = _format_prior_block(prior_segments or [])
    body = f"""
# あなたの仕事
番組のまとめ（最後の 2 分）を A と B の対話で書いてください。
- これまでの {len(show_spec.topics)} つのトピックを軽く振り返る
- conclusion_message を反映する
- 視聴後のアクションを示唆する
- 4-8 ターンが目安

# 番組情報
title: {show_spec.title}
angle: {show_spec.angle}
conclusion_message: {show_spec.conclusion_message}
{prior_block}"""
    return _HEADER + body + _FOOTER


def _format_claims(topic: TopicSpec) -> str:
    """key_claims を inline 形式で整形する (C6 修正後: [src=N] のみ、tier/confidence は別ブロック)。

    LLM が `[src=N][TIER][confidence]` 形式の inline メタデータを台本本文に
    そのまま echo して捏造数値にも信頼タグを付与する事象を観測したため、
    inline は `[src=N]` のみに簡素化。tier/confidence は `_format_claim_metadata`
    で別ブロックに分離。
    """
    if not topic.key_claims:
        return "- (該当なし)"
    return "\n".join(
        f"- [src={c.source_idx}] {c.text}"
        for c in topic.key_claims
    )


def _format_claim_metadata(topic: TopicSpec) -> str:
    """key_claims の tier/confidence を内部参照用ブロックとして整形する (C6 新設)。

    LLM への指示は「このブロックは内部参照、本文には書かない」。
    本文 inline では `[src=N]` のみが描画される (`_format_claims` 参照)。
    """
    if not topic.key_claims:
        return "(該当なし)"
    return "\n".join(
        f"- src={c.source_idx}: tier={c.source_tier}, confidence={c.confidence}"
        for c in topic.key_claims
    )


def _format_prior_segments(prior_segments: list[ScriptSegment]) -> str:
    """前 segment の **全 turn** をラベル付きで連結。

    完全 sequential 化 (backlog §6) のため、各 segment は前段の実テキストを
    full text で受け取る。32K context 上限に対し v1 規模 (~7500 chars) では
    十分な余裕がある (radio_director_design.md §13.6 max_tokens 決定指針)。
    """
    blocks: list[str] = []
    for seg in prior_segments:
        if seg.segment_type == "intro":
            label = "[intro]"
        elif seg.segment_type == "deep_dive":
            label = f"[topic {(seg.topic_index or 0) + 1}: {seg.title}]"
        else:
            label = f"[{seg.segment_type}]"
        body = "\n".join(f"  {t.speaker}: {t.text}" for t in seg.turns)
        blocks.append(f"{label}\n{body}")
    return "\n\n".join(blocks)


def _format_prior_block(prior_segments: list[ScriptSegment]) -> str:
    """prior_segments がある場合に「これまでの台本」ブロックを返す。空ならパディング無し。"""
    if not prior_segments:
        return ""
    return (
        "\n# これまでの台本（流れを踏まえる参考、引用元にはしない）\n"
        + _format_prior_segments(prior_segments)
        + "\n"
    )
