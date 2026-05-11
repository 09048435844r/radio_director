"""CleanedResearch から LLM プロンプトを組み立てる。

仕様:
- radio_director_design.md §13.2 のサンプル構造を踏襲
- §19 の必須要件「数値・固有名詞・統計を引用する場合は structured_facts から
  選ぶこと」をプロンプトに必ず明示
- §16 注意事項4 の「angle 再解釈・改変禁止」を明示
- §22.4 第1段階に従い structured_facts は全件渡し

C2 (Step 7): Pass2 由来の捏造数値が research_content に混入し、Phase B LLM が
soft 制約 (「参考情報は引用元にしない」) を無視して ShowSpec.key_claims に
転用する事象を観測。research_content を prompt 注入前に正規表現で数値除去
(`_strip_numbers_for_phase_b`) し、structured_facts のみを数値ソースとする
よう Phase B プロンプトを明示。年号 (2024年 等) は時系列情報として残す。

C5 (Step 7): ファクトが豊富なテーマで Phase B prompt が 53k chars に達し
proxy が 400 Bad Request を返す事象を観測 (diabetes2 brief)。
prompt 組み立て後にサイズチェックし、PHASE_B_PROMPT_CHAR_LIMIT を超える場合
structured_facts を confidence 優先で上位 K 件に絞り再構築する。
"""

from __future__ import annotations

import logging
import re

from radio_director import config as _config
from radio_director.models.cleaned_research import (
    CleanedFacts,
    CleanedResearch,
    ResolvedFact,
)
from radio_director.models.research_brief import Controversy, ResearchSource

logger = logging.getLogger(__name__)

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

# 数値の取り扱い (厳守 - C2)
- **参考情報 (research_content) は数値を `{strip_placeholder}` プレースホルダに置換済み**
- 具体的数値・統計を key_claims に書く場合は、必ず「主要な事実 (structured_facts)」
  から引用すること
- **structured_facts に存在しない数値を key_claims に出力しないこと**
- 参考情報の文脈は読み取って良いが、数値や統計値の引用元には絶対にしない
- 「参考情報」セクションは文脈理解にのみ使う
- リサーチ素材にない情報は絶対に補足しないでください
- B 級ソースは慎重に扱い、A 以上を優先してください
- 企画の切り口（angle）は与えられたものをそのまま尊重し、再解釈・改変しないでください
- [REVIEW] が付いた事実は精度に疑義があるため引用は慎重に
- 企画は angle を中心に組み立て、angle と無関係な事実は割愛してかまいません
- **thumbnail_title は title の核心を凝縮した 15 字以内の自然な日本語**
  にしてください。title の機械的な切り詰めや「…」での省略は禁止。
  単独で読まれてもサムネ用語として意味が通る短縮表現にすること。
- **3 つの深掘りトピックは内容範囲が重複しないこと**。同じ事実・数値・
  structured_facts の同 source_idx を別 topic で再利用しないでください。
  各 topic は独立した切り口を持ち、視聴者が「同じ話を聞いた」と感じない
  構成にしてください。
- topic 間の区別軸は「階層（前提→応用）」「対比（賛否・新旧）」「深さ
  （概要→詳細）」のいずれかで明確に分離すること。

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
    """Phase B プロンプトを組み立てる。

    C5: prompt サイズが PHASE_B_PROMPT_CHAR_LIMIT を超える場合、
    structured_facts を confidence 優先で上位 K 件に絞り再構築する。
    """
    research_content = cleaned.research_content
    placeholder = _config.PHASE_B_STRIP_PLACEHOLDER
    if _config.PHASE_B_STRIP_NUMBERS:
        research_content = _strip_numbers_for_phase_b(
            research_content, placeholder=placeholder
        )

    def _render(facts: CleanedFacts) -> str:
        return _TEMPLATE.format(
            theme=cleaned.theme,
            angle=cleaned.angle,
            formatted_facts=_format_facts(facts),
            formatted_sources=_format_sources(cleaned.sources),
            research_content=research_content,
            strip_placeholder=placeholder,
            json_schema=_JSON_SCHEMA_HINT,
        )

    prompt = _render(cleaned.facts)

    # C5: サイズガード。閾値超過なら structured_facts を上位 K 件に絞り再構築。
    limit = _config.PHASE_B_PROMPT_CHAR_LIMIT
    if limit and len(prompt) > limit:
        truncated_facts = _truncate_facts(cleaned.facts, top_k=_config.PHASE_B_FACTS_TOP_K)
        new_prompt = _render(truncated_facts)
        logger.warning(
            "Phase B prompt サイズガード発火: %d chars > 閾値 %d → "
            "structured_facts を top %d 件に絞り再構築 → %d chars",
            len(prompt),
            limit,
            _config.PHASE_B_FACTS_TOP_K,
            len(new_prompt),
        )
        prompt = new_prompt

    return prompt


# ─── C5: structured_facts truncation (confidence 優先で上位 K 件) ──────────
_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


def _sort_facts_by_priority(facts: list[ResolvedFact]) -> list[ResolvedFact]:
    """confidence (high→medium→low) → cross_validated_sources 数 (desc) →
    source_idx (asc) の優先順でソートする。"""
    def key(f: ResolvedFact):
        cvs_count = len(f.raw.get("cross_validated_sources", []) or [])
        return (
            _CONFIDENCE_RANK.get(f.confidence, 3),
            -cvs_count,
            f.source_idx,
        )

    return sorted(facts, key=key)


def _truncate_facts(facts: CleanedFacts, *, top_k: int) -> CleanedFacts:
    """各カテゴリの facts を優先順位で top_k 件に絞り、新 CleanedFacts を返す。"""
    return CleanedFacts(
        key_numbers=_sort_facts_by_priority(list(facts.key_numbers))[:top_k],
        key_entities=_sort_facts_by_priority(list(facts.key_entities))[:top_k],
        surprising_claims=_sort_facts_by_priority(list(facts.surprising_claims))[:top_k],
        controversies=list(facts.controversies),  # controversies は別データ型、そのまま
    )


# ─── C2: research_content の数値プレースホルダ置換 ────────────────────────
# 年号 ("2024年") は時系列情報として残し、それ以外の数値統計を placeholder 化する。
# 統計量パターン (n=, p<, OR=, 95%CI, HR=, RR= 等) は値ごと丸ごと placeholder に。
# 単位付き数値 ("27mm") は数値部分のみ placeholder + 単位は残す。

_YEAR_TOKEN_RE = re.compile(r"(?:19|20)\d{2}\s*年")
_STAT_NOTATION_RE = re.compile(
    r"(?:"
    r"n\s*=\s*[\d,]+(?:\.\d+)?"
    r"|p\s*[<>=]\s*0?\.\d+"
    r"|(?:OR|HR|RR|SMD)\s*[=＝]\s*-?\d+(?:\.\d+)?"
    r"|95\s*%?\s*CI"
    r")",
    flags=re.IGNORECASE,
)
# 単位付き数値: 数字 (+ カンマ + 小数) + 単位
# 単位: %, ‰, 倍, 人, 件, 円, ドル, mm, cm, m, km, kg, g, W, kW, MW, GW,
#       時間, 分, 秒, 日 (年は除外して別処理), 個, 台, 本, 回, 名, GB, MB, TB,
#       tokens/sec, ms 等
_NUMBER_WITH_UNIT_RE = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<unit>%|‰|倍|人|件|円|ドル|mm|cm|km|kg|kW|MW|GW|GB|MB|TB|"
    r"tokens?/sec|ms|時間|分|秒|個|台|本|回|名|m|g|W)"
)
# 単位なしの裸の数値 (カンマ・小数を含む整数)。年号と統計量を先に処理した後の残余。
_BARE_NUMBER_RE = re.compile(
    r"(?<![\d.])(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d.])"
)


def _strip_numbers_for_phase_b(text: str, *, placeholder: str) -> str:
    """research_content から数値統計を placeholder に置換する (年号は保持)。

    処理順序:
    1. 年号 "2024年" 等を一時マーカに退避 (置換対象外として保護)
    2. 統計量表記 (n=, p<, OR=, 95%CI 等) を丸ごと placeholder
    3. 単位付き数値 ("27mm" → "[placeholder]mm")
    4. 裸の数値 ("1,250" → "[placeholder]")
    5. 年号マーカを復元
    """
    if not text:
        return text

    # 1. 年号を non-digit marker に退避
    # marker は \x01...\x02 で囲み、index 部分は a-z で表現 (digit を含めない)。
    # 1000 件超の年号は想定しない (research_content 最大 50k chars)。
    def _idx_to_letters(idx: int) -> str:
        # 26 進数表記 (a=0, b=1, ..., z=25, aa=26, ...)
        letters = []
        n = idx
        while True:
            letters.append(chr(ord("a") + (n % 26)))
            n //= 26
            if n == 0:
                break
        return "".join(reversed(letters))

    years: list[str] = []

    def _save_year(m: "re.Match[str]") -> str:
        years.append(m.group(0))
        return f"\x01YMARK{_idx_to_letters(len(years) - 1)}\x02"

    protected = _YEAR_TOKEN_RE.sub(_save_year, text)

    # 2. 統計量表記を placeholder で置換
    protected = _STAT_NOTATION_RE.sub(placeholder, protected)

    # 3. 単位付き数値: 数値部分のみ placeholder、単位は残す
    protected = _NUMBER_WITH_UNIT_RE.sub(
        lambda m: f"{placeholder}{m.group('unit')}", protected
    )

    # 4. 裸の数値を placeholder で置換 (年号 marker は a-z のみで digit を含まない)
    protected = _BARE_NUMBER_RE.sub(placeholder, protected)

    # 5. 年号 marker を復元
    for i, y in enumerate(years):
        protected = protected.replace(f"\x01YMARK{_idx_to_letters(i)}\x02", y)

    return protected


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
