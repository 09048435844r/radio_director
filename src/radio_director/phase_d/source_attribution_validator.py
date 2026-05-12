"""C3 (Step 8): ShowSpec.key_claims の source_idx が実際にその数値・固有名詞を
含むソースを指しているかを deterministic にチェックする。

Phase B が当てずっぽうで source_idx を割り当てる挙動 (barefoot brief で
医学統計が src=8 ZICO Trust に帰属) を検出する。
LLM / embedding 不使用、純粋な文字列マッチ + 数値近似マッチ。

判定ロジック (各 claim について):
1. claim.text から数値トークン / 固有名詞候補を抽出
2. 各トークンについて、以下のいずれかが成立するかを確認:
   A. structured_facts (key_numbers.value / key_entities.name) に存在
   B. claim.source_idx が指す source (sources[idx-1]) の title / snippet に含まれる
3. A も B も成立しない token があれば source_attribution_mismatch 警告
   ただし C3_REQUIRE_ENTITY_MATCH=False の場合、固有名詞ミスマッチは warning にしない
"""

from __future__ import annotations

import re

from radio_director import config as _config
from radio_director.models.cleaned_research import CleanedResearch
from radio_director.models.show_spec import ShowSpec
from radio_director.models.verified_script import VerificationWarning

# 数値トークン (整数 / 小数 / カンマ区切り)
_NUMBER_RE = re.compile(r"(?<![\d.])(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d.])")
# 統計表記
_STAT_RE = re.compile(
    r"(?:n\s*=\s*\d+(?:,\d+)*|p\s*[<>=]\s*0?\.\d+|"
    r"(?:OR|HR|RR|SMD)\s*[=＝]\s*-?\d+(?:\.\d+)?)",
    flags=re.IGNORECASE,
)
# 固有名詞候補: 連続するカタカナ 4 文字以上 / 大文字始まり英単語 2 連続以上
_ENTITY_KATAKANA_RE = re.compile(r"[ァ-ヶー]{4,}")
_ENTITY_LATIN_RE = re.compile(r"(?:[A-Z][A-Za-z0-9]+\s+){1,3}[A-Z][A-Za-z0-9]+")


def check_source_attribution(
    show_spec: ShowSpec, cleaned_research: CleanedResearch
) -> list[VerificationWarning]:
    """ShowSpec.topics[].key_claims の source attribution を deterministic に検証する。

    Args:
        show_spec: Phase B 出力
        cleaned_research: Phase A 出力 (sources / facts を参照)

    Returns:
        source_attribution_mismatch warning のリスト (空ならすべて整合)
    """
    if not _config.C3_ENABLE:
        return []

    warnings: list[VerificationWarning] = []

    # structured_facts の値集合を構築
    sf_numbers = _collect_sf_numbers(cleaned_research)
    sf_entities = _collect_sf_entities(cleaned_research)

    n_sources = len(cleaned_research.sources)
    tolerance = float(_config.C3_NUMBER_TOLERANCE_PCT) / 100.0

    for topic_idx, topic in enumerate(show_spec.topics):
        for claim_idx, claim in enumerate(topic.key_claims):
            text = claim.text
            src_idx = claim.source_idx

            # source の snippet/title を取得
            source_text = ""
            if 1 <= src_idx <= n_sources:
                src = cleaned_research.sources[src_idx - 1]
                source_text = f"{src.title or ''} {src.snippet or ''}"

            # 数値ミスマッチをチェック
            number_tokens = _extract_number_tokens(text)
            unmatched_numbers: list[str] = []
            for token in number_tokens:
                if _number_matches(token, sf_numbers, tolerance):
                    continue
                if _number_matches(token, _extract_number_tokens(source_text), tolerance):
                    continue
                unmatched_numbers.append(token)

            # 固有名詞ミスマッチをチェック (REQUIRE_ENTITY_MATCH=True のときのみ)
            unmatched_entities: list[str] = []
            if _config.C3_REQUIRE_ENTITY_MATCH:
                entity_tokens = _extract_entity_tokens(text)
                for token in entity_tokens:
                    if token in sf_entities:
                        continue
                    if token.lower() in source_text.lower():
                        continue
                    unmatched_entities.append(token)

            if unmatched_numbers or unmatched_entities:
                detail_parts = []
                if unmatched_numbers:
                    detail_parts.append(f"unmatched_numbers={unmatched_numbers[:3]}")
                if unmatched_entities:
                    detail_parts.append(f"unmatched_entities={unmatched_entities[:3]}")
                warnings.append(
                    VerificationWarning(
                        code="source_attribution_mismatch",
                        message=(
                            f"topic[{topic_idx}].key_claims[{claim_idx}] (src={src_idx}) "
                            f"の数値・固有名詞が structured_facts にも source snippet にも "
                            f"見当たりません: {' / '.join(detail_parts)}"
                        ),
                        location=f"topic_{topic_idx}_claim_{claim_idx}",
                    )
                )

    return warnings


def _collect_sf_numbers(cleaned: CleanedResearch) -> set[float]:
    """structured_facts.key_numbers の value を float 集合として抽出する。"""
    out: set[float] = set()
    for fact in cleaned.facts.key_numbers:
        val = fact.raw.get("value", "")
        if not isinstance(val, str):
            val = str(val)
        try:
            out.add(float(val.replace(",", "").strip()))
        except (ValueError, TypeError):
            continue
    return out


def _collect_sf_entities(cleaned: CleanedResearch) -> set[str]:
    """structured_facts.key_entities の name を文字列集合として抽出する。"""
    out: set[str] = set()
    for fact in cleaned.facts.key_entities:
        name = fact.raw.get("name", "")
        if isinstance(name, str) and name.strip():
            out.add(name.strip())
    return out


def _extract_number_tokens(text: str) -> list[str]:
    """テキストから数値トークン (文字列形式) を抽出する。"""
    if not text:
        return []
    tokens: list[str] = []
    # 統計表記 (n=1,250 / OR=0.85 等) は値部分を取り出す
    for m in _STAT_RE.finditer(text):
        token = m.group(0)
        num_m = re.search(r"-?\d+(?:,\d+)*(?:\.\d+)?", token)
        if num_m:
            tokens.append(num_m.group(0))
    # 通常の数値
    for m in _NUMBER_RE.finditer(text):
        tokens.append(m.group(0))
    return tokens


def _extract_entity_tokens(text: str) -> list[str]:
    """テキストから固有名詞候補を抽出する。"""
    if not text:
        return []
    tokens: list[str] = []
    for m in _ENTITY_KATAKANA_RE.finditer(text):
        tokens.append(m.group(0))
    for m in _ENTITY_LATIN_RE.finditer(text):
        tokens.append(m.group(0))
    return tokens


def _number_matches(token: str, target_numbers: set[float] | list[str], tolerance: float) -> bool:
    """token (str) が target の数値集合と (tolerance% 内で) マッチするか。

    target_numbers が list[str] の場合は内部で float 変換する。
    """
    try:
        val = float(token.replace(",", "").strip())
    except (ValueError, TypeError):
        return False

    # target を float set に
    if isinstance(target_numbers, set):
        targets = target_numbers
    else:
        targets = set()
        for s in target_numbers:
            try:
                targets.add(float(str(s).replace(",", "").strip()))
            except (ValueError, TypeError):
                continue

    for target in targets:
        if target == 0:
            if val == 0:
                return True
            continue
        if abs(val - target) / abs(target) <= tolerance:
            return True
    return False
