"""CleanedResearch から LLM プロンプトを組み立てる。

仕様:
- radio_director_design.md §13.2 のサンプル構造を踏襲
- §19 の必須要件「数値・固有名詞・統計を引用する場合は structured_facts から
  選ぶこと」をプロンプトに必ず明示
- §16 注意事項4 の「angle 再解釈・改変禁止」を明示
- §22.4 第1段階に従い structured_facts は全件渡し
"""

from __future__ import annotations

from radio_director.models.cleaned_research import (
    CleanedFacts,
    CleanedResearch,
    ResolvedFact,
)
from radio_director.models.research_brief import Controversy, ResearchSource

_TEMPLATE = """あなたは経験豊富なラジオ番組ディレクターです。

# 番組仕様
- 配信先: YouTube ラジオ
- 出演者:
  - ずんだもん (A): 好奇心旺盛、視聴者代表として「えーっ？」と驚く役
  - 四国めたん (B): 解説役、専門知識を分かりやすく伝える
- 雰囲気: 「驚き」と「学び」のバランス
- 視聴ターゲット: 知的好奇心の高い社会人

# あなたの仕事
リサーチ素材を元に、30 分ラジオ番組の企画書を書いてください。

企画書には以下の構成が必要です:
- 番組タイトル（視聴者がクリックしたくなるもの）
- サムネ用短縮タイトル（thumbnail_title、15 字以内、サムネ画像に重ねる短い表現）
- イントロ（最初の 2 分で視聴者の関心をつかむフック）
- 深掘りトピック × 3（各 7-8 分）
- まとめ（視聴後のアクションを示唆）

各トピックには:
- 魅力的なタイトル
- 「実は〇〇」というフック
- 根拠となる事実（3-5 個、出典タグ付き）
- そのトピックのトーン（驚き / 議論 / 解説 など）

# 重要なルール
- 番組の信頼性のため、各事実には [AAA]/[AA]/[A]/[B] の出典タグを付けてください
- **数値・固有名詞・統計を引用する場合は「主要な事実」セクションから選んでください**
- 「参考情報」セクションは文脈理解にのみ使い、数値や固有名詞の引用元にしないでください
- リサーチ素材にない情報は絶対に補足しないでください
- B 級ソースは慎重に扱い、A 以上を優先してください
- 企画の切り口（angle）は与えられたものをそのまま尊重し、再解釈・改変しないでください
- [REVIEW] が付いた事実は精度に疑義があるため引用は慎重に
- 企画は angle を中心に組み立て、angle と無関係な事実は割愛してかまいません
- **thumbnail_title は title の核心を凝縮した 15 字以内の自然な日本語**
  にしてください。title の機械的な切り詰めや「…」での省略は禁止。
  単独で読まれてもサムネ用語として意味が通る短縮表現にすること。

# テーマ
{theme}

# 切り口（angle）
{angle}

# 主要な事実 (structured_facts、引用は必ずここから)
{formatted_facts}

# ソース一覧 (source_idx -> tier)
{formatted_sources}

# 参考情報 (research_content、文脈理解用)
{research_content}

# 出力フォーマット (JSON、以下のスキーマに厳密に従うこと)
{json_schema}
"""

_JSON_SCHEMA_HINT = """{
  "title": "番組タイトル",
  "thumbnail_title": "サムネ用短縮タイトル（15 字以内、必須）",
  "hook": "イントロのフック（2分で視聴者を掴む問い）",
  "angle": "上の angle をそのまま転記する（再解釈禁止）",
  "arc": "番組全体のアーク（導入→深掘り→まとめの流れ）",
  "tone": "番組全体のトーン",
  "topics": [
    {
      "title": "トピックのタイトル",
      "hook": "実は〇〇という形式のフック",
      "key_claims": [
        {
          "text": "事実の説明（出典タグ付き、例: 「睡眠不足者の感染率は2.94倍 [AAA]」）",
          "source_idx": 3,
          "source_tier": "AAA",
          "confidence": "medium"
        }
      ],
      "tone": "驚き / 議論 / 解説 など",
      "estimated_turns": 14
    }
  ],
  "conclusion_message": "視聴後のアクションを示唆するまとめ"
}"""


def build_prompt(cleaned: CleanedResearch) -> str:
    return _TEMPLATE.format(
        theme=cleaned.theme,
        angle=cleaned.angle,
        formatted_facts=_format_facts(cleaned.facts),
        formatted_sources=_format_sources(cleaned.sources),
        research_content=cleaned.research_content,
        json_schema=_JSON_SCHEMA_HINT,
    )


def _format_facts(facts: CleanedFacts) -> str:
    sections: list[str] = []

    sections.append("## key_numbers")
    if facts.key_numbers:
        sections.extend(_format_resolved(f) for f in facts.key_numbers)
    else:
        sections.append("- (該当なし)")

    sections.append("")
    sections.append("## key_entities")
    if facts.key_entities:
        sections.extend(_format_resolved(f) for f in facts.key_entities)
    else:
        sections.append("- (該当なし)")

    sections.append("")
    sections.append("## surprising_claims")
    if facts.surprising_claims:
        sections.extend(_format_resolved(f) for f in facts.surprising_claims)
    else:
        sections.append("- (該当なし)")

    sections.append("")
    sections.append("## controversies")
    if facts.controversies:
        sections.extend(_format_controversy(c) for c in facts.controversies)
    else:
        sections.append("- (該当なし)")

    return "\n".join(sections)


def _format_resolved(fact: ResolvedFact) -> str:
    tags = [
        f"src={fact.source_idx}",
        fact.primary_source_tier,
        fact.confidence,
    ]
    for flag in fact.flags:
        tags.append(flag)
    if fact.needs_review:
        tags.append("REVIEW")
    return f"- [{']['.join(tags)}] {fact.text}"


def _format_controversy(controversy: Controversy) -> str:
    sources = ",".join(str(i) for i in controversy.source_indices)
    return (
        f"- 立場A: {controversy.position_a} / "
        f"立場B: {controversy.position_b} (sources=[{sources}])"
    )


def _format_sources(sources: list[ResearchSource]) -> str:
    lines: list[str] = []
    for i, source in enumerate(sources, start=1):
        domain = _extract_domain(source.url)
        lines.append(f"[{i}] {source.domain_tier} {domain} - {source.title}")
    return "\n".join(lines)


def _extract_domain(url: str) -> str:
    if "://" in url:
        url = url.split("://", 1)[1]
    return url.split("/", 1)[0]
