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
- A (ずんだもん): 好奇心旺盛、視聴者代表。語尾「のだ」「のだー」を多用。
- B (四国めたん): 解説役、専門知識を分かりやすく伝える。語尾「だわ」「ですわ」を多用。

# 共通ルール
- 数値・固有名詞・統計を引用する場合は提供された key_claims から選んでください
- 各 claim には出典タグ [AAA]/[AA]/[A]/[B] を台本中で明示してください
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


def build_deep_dive_prompt(show_spec: ShowSpec, topic_index: int) -> str:
    topic = show_spec.topics[topic_index]
    body = f"""
# あなたの仕事
トピック「{topic.title}」を A と B の対話で深掘りしてください（7-8 分相当）。
- フック「{topic.hook}」から始める
- 提供された key_claims を必ず引用する（出典タグ付き）
- トピックのトーン: {topic.tone}
- {topic.estimated_turns} ターン前後を目安に、12-18 ターンの範囲で

# 番組コンテキスト
title: {show_spec.title}
angle: {show_spec.angle}

# トピック詳細
title: {topic.title}
hook: {topic.hook}
tone: {topic.tone}

# key_claims (引用は必ずここから)
{_format_claims(topic)}
"""
    return _HEADER + body + _FOOTER


def build_conclusion_prompt(
    show_spec: ShowSpec, prior_segments: list[ScriptSegment]
) -> str:
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

# これまでの台本（要約として参照、引用元にはしない）
{_format_prior_summary(prior_segments)}
"""
    return _HEADER + body + _FOOTER


def _format_claims(topic: TopicSpec) -> str:
    if not topic.key_claims:
        return "- (該当なし)"
    return "\n".join(
        f"- [src={c.source_idx}][{c.source_tier}][{c.confidence}] {c.text}"
        for c in topic.key_claims
    )


def _format_prior_summary(prior_segments: list[ScriptSegment]) -> str:
    blocks: list[str] = []
    for seg in prior_segments:
        if seg.segment_type == "intro":
            label = "[intro]"
        elif seg.segment_type == "deep_dive":
            label = f"[topic {(seg.topic_index or 0) + 1}: {seg.title}]"
        else:
            label = f"[{seg.segment_type}]"
        excerpt_turns = seg.turns[:4]
        excerpt = "\n".join(f"  {t.speaker}: {t.text}" for t in excerpt_turns)
        blocks.append(f"{label}\n{excerpt}")
    return "\n\n".join(blocks)
